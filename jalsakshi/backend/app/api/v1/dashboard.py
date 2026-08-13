"""Console summary.

Everything here is derived from the same tables the rest of the API serves; it
exists so the operations console can draw its header tiles in one request
instead of six, not so it can learn anything the other endpoints hide. In
particular it reads `fault_events` (what the classifier concluded) and never
`fault_injections` (what the simulator did).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.analytics.pipeline import DetectionError
from app.api.deps import DetectionDep, RepositoryDep
from app.schemas.workorder import WorkOrderStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

#: Statuses that mean the network is not yet known to be serving water again.
_OPEN_STATUSES = tuple(
    s
    for s in WorkOrderStatus
    if s not in (WorkOrderStatus.CLOSED,)
)


class SeverityCounts(BaseModel):
    critical: int = 0
    warning: int = 0
    info: int = 0


class SensorTrust(BaseModel):
    total: int = 0
    trusted: int = 0
    untrusted: list[str] = Field(default_factory=list)


class DashboardSummary(BaseModel):
    """One request behind the console's header tiles."""

    service_area_id: str
    service_area_code: str
    service_area_name: str
    generated_at: datetime

    #: Households in the service area — the denominator for "how bad is this".
    service_area_households: int | None = None

    open_incidents: int = 0
    incident_severity: SeverityCounts = Field(default_factory=SeverityCounts)
    households_affected: int = 0
    #: Households without supply, per zone asset code.
    households_by_zone: dict[str, int] = Field(default_factory=dict)

    open_work_orders: int = 0
    work_orders_by_status: dict[str, int] = Field(default_factory=dict)
    sla_breached: int = 0

    #: The clock the console shows: minutes since the oldest open incident.
    active_ttwr_minutes: float | None = None
    active_incident_id: str | None = None
    #: Mean TTWR over work orders closed in the reporting window.
    mean_ttwr_minutes: float | None = None
    closed_in_window: int = 0
    reopened_in_window: int = 0
    #: Closures that verification sent back — the number this product exists to
    #: make non-zero rather than invisible.
    reopen_rate: float = 0.0

    sensors: SensorTrust = Field(default_factory=SensorTrust)
    #: 0-100. Falls with untrusted instruments, open criticals and SLA breaches.
    water_health_score: int = 100
    network_uptime_pct: float = 100.0

    budget_allocated: float | None = None
    budget_remaining: float | None = None
    autonomous_approval_limit: float | None = None
    currency: str = "INR"


def _severity_bucket(severity_score: float) -> str:
    if severity_score >= 0.66:
        return "critical"
    if severity_score >= 0.33:
        return "warning"
    return "info"


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    repository: RepositoryDep,
    detection: DetectionDep,
    hours: int = Query(72, ge=1, le=336, description="Reporting window"),
) -> DashboardSummary:
    try:
        await detection.load()
    except DetectionError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    area = await repository.get_service_area(detection.service_area_id)
    if area is None:  # pragma: no cover - detection.load() guarantees it
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="service area not found"
        )

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    events = await repository.list_fault_events(
        service_area_id=area.id, since=since, limit=500
    )
    orders = await repository.list_work_orders(service_area_id=area.id, limit=500)
    assets = {asset.id: asset for asset in await repository.list_assets(area.id)}

    open_events = [event for event in events if event.status != "RESOLVED"]
    severity = SeverityCounts()
    households_by_zone: dict[str, int] = {}
    for event in open_events:
        setattr(
            severity,
            _severity_bucket(event.severity_score),
            getattr(severity, _severity_bucket(event.severity_score)) + 1,
        )
        asset = assets.get(event.asset_id or "")
        if event.households_affected and asset is not None:
            households_by_zone[asset.asset_code] = (
                households_by_zone.get(asset.asset_code, 0) + event.households_affected
            )

    open_orders = [order for order in orders if order.status in _OPEN_STATUSES]
    by_status: dict[str, int] = {}
    for order in orders:
        by_status[order.status.value] = by_status.get(order.status.value, 0) + 1

    closed = [
        order
        for order in orders
        if order.status is WorkOrderStatus.CLOSED
        and order.closed_at is not None
        and order.closed_at >= since
    ]
    ttwrs = [order.ttwr_minutes for order in closed if order.ttwr_minutes is not None]
    reopened = sum(1 for order in orders if order.reopen_count)

    # The headline clock: how long the oldest unresolved incident has been
    # running. It is elapsed time, not a prediction.
    active_ttwr: float | None = None
    active_incident: str | None = None
    if open_events:
        oldest = min(open_events, key=lambda event: event.detected_at)
        active_incident = oldest.id
        active_ttwr = (now - oldest.detected_at).total_seconds() / 60

    try:
        health = await detection.sensor_health()
    except DetectionError:
        health = []
    untrusted = [item.sensor_code for item in health if not item.trusted]
    sensors = SensorTrust(
        total=len(health), trusted=len(health) - len(untrusted), untrusted=untrusted
    )

    sla_breached = sum(1 for order in open_orders if order.sla_breached)

    # A single number for the header tile, and an honest one: it is a penalty
    # sum, not a model output, so it can be explained on stage.
    score = 100
    score -= 18 * severity.critical
    score -= 7 * severity.warning
    score -= 6 * sla_breached
    if sensors.total:
        score -= int(24 * len(untrusted) / sensors.total)
    water_health = max(0, min(100, score))

    uptime = 100.0
    if sensors.total:
        uptime = round(100.0 * sensors.trusted / sensors.total, 1)

    account = await repository.get_vwsc_account(area.id)

    return DashboardSummary(
        service_area_id=area.id,
        service_area_code=area.code,
        service_area_name=area.name,
        generated_at=now,
        service_area_households=area.households,
        open_incidents=len(open_events),
        incident_severity=severity,
        households_affected=sum(households_by_zone.values()),
        households_by_zone=households_by_zone,
        open_work_orders=len(open_orders),
        work_orders_by_status=by_status,
        sla_breached=sla_breached,
        active_ttwr_minutes=active_ttwr,
        active_incident_id=active_incident,
        mean_ttwr_minutes=(sum(ttwrs) / len(ttwrs)) if ttwrs else None,
        closed_in_window=len(closed),
        reopened_in_window=reopened,
        reopen_rate=round(reopened / len(orders), 3) if orders else 0.0,
        sensors=sensors,
        water_health_score=water_health,
        network_uptime_pct=uptime,
        budget_allocated=account.budget_allocated if account else None,
        budget_remaining=account.budget_remaining if account else None,
        autonomous_approval_limit=(
            account.autonomous_approval_limit if account else None
        ),
    )
