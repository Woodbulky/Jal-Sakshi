"""In-memory `Repository` used by the offline test suite.

Same semantics as `SupabaseRepository`, no network. Nothing in production
should construct this.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.schemas.detection import Anomaly, FaultEvent
from app.schemas.network import (
    Asset,
    AssetConnection,
    Sensor,
    SensorReading,
    ServiceArea,
)
from app.schemas.notification import Notification, NotificationDirection
from app.schemas.simulation import FaultInjection, FaultType
from app.schemas.workorder import (
    Assignment,
    AssetHealth,
    DecisionEntry,
    Escalation,
    VwscAccount,
    WorkOrder,
    WorkOrderStatus,
)
from app.workorders.state_machine import assert_transition


class InMemoryRepository:
    def __init__(
        self,
        *,
        service_areas: list[ServiceArea] | None = None,
        assets: list[Asset] | None = None,
        connections: list[AssetConnection] | None = None,
        sensors: list[Sensor] | None = None,
        readings: list[SensorReading] | None = None,
        fault_injections: list[FaultInjection] | None = None,
        anomalies: list[Anomaly] | None = None,
        fault_events: list[FaultEvent] | None = None,
        work_orders: list[WorkOrder] | None = None,
        assignments: list[Assignment] | None = None,
        escalations: list[Escalation] | None = None,
        notifications: list[Notification] | None = None,
        decisions: list[DecisionEntry] | None = None,
        asset_health: list[AssetHealth] | None = None,
        vwsc_accounts: list[VwscAccount] | None = None,
    ) -> None:
        self.service_areas = list(service_areas or [])
        self.assets = list(assets or [])
        self.connections = list(connections or [])
        self.sensors = list(sensors or [])
        self.readings = sorted(readings or [], key=lambda r: r.ts)
        self.fault_injections = list(fault_injections or [])
        self.anomalies = list(anomalies or [])
        self.fault_events = list(fault_events or [])
        self.work_orders = list(work_orders or [])
        self.assignments = list(assignments or [])
        self.escalations = list(escalations or [])
        self.notifications = list(notifications or [])
        self.decisions = list(decisions or [])
        self.asset_health = list(asset_health or [])
        self.vwsc_accounts = list(vwsc_accounts or [])

    async def list_service_areas(self) -> list[ServiceArea]:
        return sorted(self.service_areas, key=lambda area: area.name)

    async def get_service_area(self, ref: str) -> ServiceArea | None:
        for area in self.service_areas:
            if ref in (area.id, area.code):
                return area
        return None

    async def list_assets(self, service_area_id: str) -> list[Asset]:
        return sorted(
            (a for a in self.assets if a.service_area_id == service_area_id),
            key=lambda a: a.asset_code,
        )

    async def get_asset(
        self, ref: str, service_area_id: str | None = None
    ) -> Asset | None:
        for asset in self.assets:
            if ref not in (asset.id, asset.asset_code):
                continue
            if service_area_id and asset.service_area_id != service_area_id:
                continue
            return asset
        return None

    async def list_connections(self, service_area_id: str) -> list[AssetConnection]:
        return [c for c in self.connections if c.service_area_id == service_area_id]

    async def list_sensors(
        self,
        *,
        service_area_id: str | None = None,
        asset_id: str | None = None,
    ) -> list[Sensor]:
        sensors = self.sensors
        if asset_id:
            sensors = [s for s in sensors if s.asset_id == asset_id]
        elif service_area_id:
            asset_ids = {
                a.id for a in self.assets if a.service_area_id == service_area_id
            }
            sensors = [s for s in sensors if s.asset_id in asset_ids]
        return sorted(sensors, key=lambda s: s.sensor_code)

    async def get_sensor(self, ref: str) -> Sensor | None:
        for sensor in self.sensors:
            if ref in (sensor.id, sensor.sensor_code):
                return sensor
        return None

    async def latest_readings(self, sensor_ids: list[str]) -> dict[str, SensorReading]:
        wanted = set(sensor_ids)
        latest: dict[str, SensorReading] = {}
        for reading in self.readings:  # ascending, so the last write wins
            if reading.sensor_id in wanted:
                latest[reading.sensor_id] = reading
        return latest

    async def list_readings(
        self,
        sensor_ids: list[str],
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[SensorReading]:
        wanted = set(sensor_ids)
        selected = [
            r
            for r in self.readings
            if r.sensor_id in wanted
            and (start is None or r.ts >= start)
            and (end is None or r.ts <= end)
        ]
        if len(selected) > limit:
            selected = selected[-limit:]  # newest `limit` points
        return selected

    # -- simulator writes --------------------------------------------------
    async def insert_readings(
        self,
        readings: Sequence[SensorReading],
        *,
        fault_run_id: str | None = None,
    ) -> int:
        if not readings:
            return 0
        # Mirror the (sensor_id, ts) unique constraint so re-running a backfill
        # behaves the same offline as it does against Postgres.
        index = {(r.sensor_id, r.ts): i for i, r in enumerate(self.readings)}
        for reading in readings:
            key = (reading.sensor_id, reading.ts)
            if key in index:
                self.readings[index[key]] = reading
            else:
                index[key] = len(self.readings)
                self.readings.append(reading)
        self.readings.sort(key=lambda r: r.ts)
        return len(readings)

    async def create_fault_injection(
        self,
        *,
        service_area_id: str,
        fault_type: FaultType,
        asset_id: str | None = None,
        started_at: datetime | None = None,
        ends_at: datetime | None = None,
        params: dict[str, Any] | None = None,
    ) -> FaultInjection:
        injection = FaultInjection(
            id=str(uuid4()),
            service_area_id=service_area_id,
            asset_id=asset_id,
            fault_type=fault_type,
            started_at=started_at or datetime.now(timezone.utc),
            ends_at=ends_at,
            is_active=True,
            params=params or {},
        )
        self.fault_injections.append(injection)
        return injection

    async def list_fault_injections(
        self,
        *,
        service_area_id: str | None = None,
        active_only: bool = False,
    ) -> list[FaultInjection]:
        selected = [
            f
            for f in self.fault_injections
            if (service_area_id is None or f.service_area_id == service_area_id)
            and (not active_only or f.is_active)
        ]
        return sorted(selected, key=lambda f: f.started_at, reverse=True)

    async def clear_fault_injection(
        self, injection_id: str, *, cleared_at: datetime | None = None
    ) -> FaultInjection | None:
        for index, injection in enumerate(self.fault_injections):
            if injection.id != injection_id:
                continue
            cleared = injection.model_copy(
                update={
                    "is_active": False,
                    "cleared_at": cleared_at or datetime.now(timezone.utc),
                }
            )
            self.fault_injections[index] = cleared
            return cleared
        return None

    # -- detection ---------------------------------------------------------
    async def insert_anomalies(self, anomalies: Sequence[Anomaly]) -> list[Anomaly]:
        stored = [
            anomaly.model_copy(update={"id": anomaly.id or str(uuid4())})
            for anomaly in anomalies
        ]
        self.anomalies.extend(stored)
        return stored

    async def update_anomaly(self, anomaly_id: str, **fields: Any) -> Anomaly | None:
        for index, anomaly in enumerate(self.anomalies):
            if anomaly.id != anomaly_id:
                continue
            updated = anomaly.model_copy(update=fields)
            self.anomalies[index] = updated
            return updated
        return None

    async def list_anomalies(
        self,
        *,
        service_area_id: str | None = None,
        since: datetime | None = None,
        status: str | None = None,
        fault_event_id: str | None = None,
        limit: int = 200,
    ) -> list[Anomaly]:
        selected = [
            a
            for a in self.anomalies
            if (service_area_id is None or a.service_area_id == service_area_id)
            and (since is None or a.detected_at >= since)
            and (status is None or a.status == status)
            and (fault_event_id is None or a.fault_event_id == fault_event_id)
        ]
        selected.sort(key=lambda a: a.detected_at, reverse=True)
        return selected[:limit]

    async def create_fault_event(self, event: FaultEvent) -> FaultEvent:
        stored = event.model_copy(
            update={
                "id": str(uuid4()),
                "created_at": event.created_at or datetime.now(timezone.utc),
            }
        )
        self.fault_events.append(stored)
        return stored

    async def update_fault_event(
        self, fault_event_id: str, **fields: Any
    ) -> FaultEvent | None:
        for index, event in enumerate(self.fault_events):
            if event.id != fault_event_id:
                continue
            updated = event.model_copy(update=fields)
            self.fault_events[index] = updated
            return updated
        return None

    async def get_fault_event(self, fault_event_id: str) -> FaultEvent | None:
        return next((e for e in self.fault_events if e.id == fault_event_id), None)

    async def list_fault_events(
        self,
        *,
        service_area_id: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[FaultEvent]:
        selected = [
            e
            for e in self.fault_events
            if (service_area_id is None or e.service_area_id == service_area_id)
            and (status is None or e.status == status)
            and (since is None or e.detected_at >= since)
        ]
        selected.sort(key=lambda e: e.detected_at, reverse=True)
        return selected[:limit]

    # -- work orders -------------------------------------------------------
    async def create_work_order(self, work_order: WorkOrder) -> WorkOrder:
        now = datetime.now(timezone.utc)
        stored = work_order.model_copy(
            update={
                "id": str(uuid4()),
                "created_at": work_order.created_at or now,
                "updated_at": now,
            }
        )
        self.work_orders.append(stored)
        return stored

    async def update_work_order(
        self, work_order_id: str, **fields: Any
    ) -> WorkOrder | None:
        for index, order in enumerate(self.work_orders):
            if order.id != work_order_id:
                continue
            # Same refusal the Postgres trigger makes, raised before the write
            # rather than after it.
            if "status" in fields:
                requested = WorkOrderStatus(fields["status"])
                assert_transition(order.status, requested, order.wo_code)
                if (
                    requested is WorkOrderStatus.REOPENED
                    and fields.get("reopen_count", order.reopen_count)
                    <= order.reopen_count
                ):
                    fields = {**fields, "reopen_count": order.reopen_count + 1}
            updated = order.model_copy(
                update={**fields, "updated_at": datetime.now(timezone.utc)}
            )
            self.work_orders[index] = updated
            return updated
        return None

    async def get_work_order(self, ref: str) -> WorkOrder | None:
        return next(
            (w for w in self.work_orders if ref in (w.id, w.wo_code)),
            None,
        )

    async def list_work_orders(
        self,
        *,
        service_area_id: str | None = None,
        status: WorkOrderStatus | None = None,
        fault_event_id: str | None = None,
        open_only: bool = False,
        limit: int = 100,
    ) -> list[WorkOrder]:
        selected = [
            w
            for w in self.work_orders
            if (service_area_id is None or w.service_area_id == service_area_id)
            and (status is None or w.status is status)
            and (fault_event_id is None or w.fault_event_id == fault_event_id)
            and (not open_only or w.is_open)
        ]
        selected.sort(key=lambda w: w.created_at or datetime.min.replace(
            tzinfo=timezone.utc
        ), reverse=True)
        return selected[:limit]

    async def next_work_order_code(self) -> str:
        return f"WO-{len(self.work_orders) + 1:03d}"

    # -- assignments and escalations ---------------------------------------
    async def create_assignment(self, assignment: Assignment) -> Assignment:
        stored = assignment.model_copy(update={"id": str(uuid4())})
        self.assignments.append(stored)
        return stored

    async def update_assignment(
        self, assignment_id: str, **fields: Any
    ) -> Assignment | None:
        for index, assignment in enumerate(self.assignments):
            if assignment.id != assignment_id:
                continue
            updated = assignment.model_copy(update=fields)
            self.assignments[index] = updated
            return updated
        return None

    async def list_assignments(
        self, *, work_order_id: str | None = None, active_only: bool = False
    ) -> list[Assignment]:
        selected = [
            a
            for a in self.assignments
            if (work_order_id is None or a.work_order_id == work_order_id)
            and (not active_only or a.released_at is None)
        ]
        return sorted(selected, key=lambda a: a.assigned_at)

    async def create_escalation(self, escalation: Escalation) -> Escalation:
        stored = escalation.model_copy(update={"id": str(uuid4())})
        self.escalations.append(stored)
        return stored

    async def update_escalation(
        self, escalation_id: str, **fields: Any
    ) -> Escalation | None:
        for index, escalation in enumerate(self.escalations):
            if escalation.id != escalation_id:
                continue
            updated = escalation.model_copy(update=fields)
            self.escalations[index] = updated
            return updated
        return None

    async def list_escalations(
        self, *, work_order_id: str | None = None, unresolved_only: bool = False
    ) -> list[Escalation]:
        selected = [
            e
            for e in self.escalations
            if (work_order_id is None or e.work_order_id == work_order_id)
            and (not unresolved_only or e.resolved_at is None)
        ]
        return sorted(selected, key=lambda e: e.triggered_at)

    # -- notifications -----------------------------------------------------
    async def create_notification(self, notification: Notification) -> Notification:
        stored = notification.model_copy(
            update={
                "id": str(uuid4()),
                "created_at": notification.created_at or datetime.now(timezone.utc),
            }
        )
        self.notifications.append(stored)
        return stored

    async def update_notification(
        self, notification_id: str, **fields: Any
    ) -> Notification | None:
        for index, notification in enumerate(self.notifications):
            if notification.id != notification_id:
                continue
            updated = notification.model_copy(update=fields)
            self.notifications[index] = updated
            return updated
        return None

    async def list_notifications(
        self,
        *,
        work_order_id: str | None = None,
        direction: NotificationDirection | None = None,
        limit: int = 100,
    ) -> list[Notification]:
        selected = [
            n
            for n in self.notifications
            if (work_order_id is None or n.work_order_id == work_order_id)
            and (direction is None or n.direction is direction)
        ]
        selected.sort(
            key=lambda n: n.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return selected[:limit]

    # -- accountability ----------------------------------------------------
    async def record_decision(self, entry: DecisionEntry) -> DecisionEntry:
        stored = entry.model_copy(update={"id": str(uuid4())})
        self.decisions.append(stored)
        return stored

    async def list_decisions(
        self,
        *,
        work_order_id: str | None = None,
        fault_event_id: str | None = None,
        limit: int = 200,
    ) -> list[DecisionEntry]:
        selected = [
            d
            for d in self.decisions
            if (work_order_id is None or d.work_order_id == work_order_id)
            and (fault_event_id is None or d.fault_event_id == fault_event_id)
        ]
        selected.sort(key=lambda d: d.ts, reverse=True)
        return selected[:limit]

    async def get_asset_health(self, asset_id: str) -> AssetHealth | None:
        return next((h for h in self.asset_health if h.asset_id == asset_id), None)

    async def upsert_asset_health(self, health: AssetHealth) -> AssetHealth:
        stored = health.model_copy(
            update={
                "id": health.id or str(uuid4()),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        for index, existing in enumerate(self.asset_health):
            if existing.asset_id == stored.asset_id:
                self.asset_health[index] = stored
                return stored
        self.asset_health.append(stored)
        return stored

    async def list_asset_health(
        self, *, service_area_id: str | None = None
    ) -> list[AssetHealth]:
        if service_area_id is None:
            return list(self.asset_health)
        asset_ids = {a.id for a in self.assets if a.service_area_id == service_area_id}
        return [h for h in self.asset_health if h.asset_id in asset_ids]

    async def get_vwsc_account(
        self, service_area_id: str, *, fiscal_year: str | None = None
    ) -> VwscAccount | None:
        matches = [
            a
            for a in self.vwsc_accounts
            if a.service_area_id == service_area_id
            and (fiscal_year is None or a.fiscal_year == fiscal_year)
        ]
        return max(matches, key=lambda a: a.fiscal_year) if matches else None

    async def update_vwsc_account(
        self, account_id: str, **fields: Any
    ) -> VwscAccount | None:
        for index, account in enumerate(self.vwsc_accounts):
            if account.id != account_id:
                continue
            updated = account.model_copy(
                update={**fields, "updated_at": datetime.now(timezone.utc)}
            )
            self.vwsc_accounts[index] = updated
            return updated
        return None
