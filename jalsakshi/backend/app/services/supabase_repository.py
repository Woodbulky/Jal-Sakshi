"""Supabase-backed implementation of `Repository`.

The service-role key is used server side only. supabase-py is synchronous, so
every call is pushed to a worker thread to keep the event loop free.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, TypeVar
from uuid import UUID

from supabase import Client, create_client

from app.core.config import Settings
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

logger = logging.getLogger(__name__)

T = TypeVar("T")

_ASSET_COLUMNS = (
    "id,service_area_id,asset_code,asset_type,name,latitude,longitude,"
    "status,households_served,commissioned_on,metadata"
)
_SENSOR_COLUMNS = (
    "id,asset_id,sensor_code,sensor_type,unit,sampling_interval_seconds,"
    "status,last_seen_at,expected_min,expected_max"
)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


class SupabaseRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> "SupabaseRepository":
        if not settings.supabase_configured:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. "
                "JAL-SAKSHI has no local database fallback."
            )
        client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        return cls(client)

    @staticmethod
    async def _run(fn: Callable[[], T]) -> T:
        return await asyncio.to_thread(fn)

    def _table(self, name: str) -> Any:
        return self._client.table(name)

    # -- service areas ----------------------------------------------------
    async def list_service_areas(self) -> list[ServiceArea]:
        rows = await self._run(
            lambda: self._table("service_areas").select("*").order("name").execute().data
        )
        return [ServiceArea.model_validate(row) for row in rows or []]

    async def get_service_area(self, ref: str) -> ServiceArea | None:
        column = "id" if _is_uuid(ref) else "code"
        rows = await self._run(
            lambda: self._table("service_areas")
            .select("*")
            .eq(column, ref)
            .limit(1)
            .execute()
            .data
        )
        return ServiceArea.model_validate(rows[0]) if rows else None

    # -- assets + topology ------------------------------------------------
    async def list_assets(self, service_area_id: str) -> list[Asset]:
        rows = await self._run(
            lambda: self._table("assets")
            .select(_ASSET_COLUMNS)
            .eq("service_area_id", service_area_id)
            .order("asset_code")
            .execute()
            .data
        )
        return [Asset.model_validate(row) for row in rows or []]

    async def get_asset(
        self, ref: str, service_area_id: str | None = None
    ) -> Asset | None:
        column = "id" if _is_uuid(ref) else "asset_code"

        def query() -> list[dict[str, Any]]:
            builder = self._table("assets").select(_ASSET_COLUMNS).eq(column, ref)
            if service_area_id:
                builder = builder.eq("service_area_id", service_area_id)
            return builder.limit(1).execute().data

        rows = await self._run(query)
        return Asset.model_validate(rows[0]) if rows else None

    async def list_connections(self, service_area_id: str) -> list[AssetConnection]:
        rows = await self._run(
            lambda: self._table("asset_connections")
            .select(
                "id,service_area_id,from_asset_id,to_asset_id,"
                "connection_type,diameter_mm,length_m"
            )
            .eq("service_area_id", service_area_id)
            .execute()
            .data
        )
        return [AssetConnection.model_validate(row) for row in rows or []]

    # -- sensors ----------------------------------------------------------
    async def list_sensors(
        self,
        *,
        service_area_id: str | None = None,
        asset_id: str | None = None,
    ) -> list[Sensor]:
        asset_ids: list[str] | None = None
        if asset_id:
            asset_ids = [asset_id]
        elif service_area_id:
            assets = await self.list_assets(service_area_id)
            asset_ids = [asset.id for asset in assets]
            if not asset_ids:
                return []

        def query() -> list[dict[str, Any]]:
            builder = self._table("sensors").select(_SENSOR_COLUMNS)
            if asset_ids is not None:
                builder = builder.in_("asset_id", asset_ids)
            return builder.order("sensor_code").execute().data

        rows = await self._run(query)
        return [Sensor.model_validate(row) for row in rows or []]

    async def get_sensor(self, ref: str) -> Sensor | None:
        column = "id" if _is_uuid(ref) else "sensor_code"
        rows = await self._run(
            lambda: self._table("sensors")
            .select(_SENSOR_COLUMNS)
            .eq(column, ref)
            .limit(1)
            .execute()
            .data
        )
        return Sensor.model_validate(rows[0]) if rows else None

    # -- readings ---------------------------------------------------------
    async def latest_readings(self, sensor_ids: list[str]) -> dict[str, SensorReading]:
        if not sensor_ids:
            return {}

        # One descending scan capped generously; the per-sensor newest point wins.
        rows = await self._run(
            lambda: self._table("sensor_readings")
            .select("sensor_id,ts,value,quality_flag")
            .in_("sensor_id", sensor_ids)
            .order("ts", desc=True)
            .limit(max(len(sensor_ids) * 20, 200))
            .execute()
            .data
        )
        latest: dict[str, SensorReading] = {}
        for row in rows or []:
            reading = SensorReading.model_validate(row)
            if reading.sensor_id not in latest:
                latest[reading.sensor_id] = reading
        return latest

    #: PostgREST caps a single response (`max-rows`, 1000 by default). The
    #: baseline query wants tens of thousands of rows, so reads are paged well
    #: under that cap rather than silently truncated.
    _READ_PAGE = 500

    async def list_readings(
        self,
        sensor_ids: list[str],
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[SensorReading]:
        if not sensor_ids or limit <= 0:
            return []

        def page(offset: int, size: int) -> list[dict[str, Any]]:
            builder = (
                self._table("sensor_readings")
                .select("sensor_id,ts,value,quality_flag")
                .in_("sensor_id", sensor_ids)
            )
            if start is not None:
                builder = builder.gte("ts", start.isoformat())
            if end is not None:
                builder = builder.lte("ts", end.isoformat())
            return (
                builder.order("ts", desc=True)
                .range(offset, offset + size - 1)
                .execute()
                .data
            )

        rows: list[dict[str, Any]] = []
        while len(rows) < limit:
            size = min(self._READ_PAGE, limit - len(rows))
            chunk = await self._run(lambda o=len(rows), s=size: page(o, s))
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < size:
                break

        readings = [SensorReading.model_validate(row) for row in rows]
        readings.reverse()  # hand back oldest -> newest for charting
        return readings

    # -- simulator writes --------------------------------------------------
    _READING_CHUNK = 500

    async def insert_readings(
        self,
        readings: Sequence[SensorReading],
        *,
        fault_run_id: str | None = None,
    ) -> int:
        if not readings:
            return 0

        payload = [
            {
                "sensor_id": r.sensor_id,
                "ts": r.ts.isoformat(),
                "value": r.value,
                "quality_flag": r.quality_flag.value,
                "is_synthetic": True,
                "fault_run_id": fault_run_id,
            }
            for r in readings
        ]

        written = 0
        for start in range(0, len(payload), self._READING_CHUNK):
            chunk = payload[start : start + self._READING_CHUNK]
            rows = await self._run(
                lambda chunk=chunk: self._table("sensor_readings")
                .upsert(chunk, on_conflict="sensor_id,ts")
                .execute()
                .data
            )
            written += len(rows or chunk)
        return written

    # -- fault injections (ground truth; never a classifier input) ---------
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
        record = {
            "service_area_id": service_area_id,
            "asset_id": asset_id,
            "fault_type": fault_type.value,
            "started_at": (started_at or datetime.now(timezone.utc)).isoformat(),
            "ends_at": ends_at.isoformat() if ends_at else None,
            "is_active": True,
            "params": params or {},
        }
        rows = await self._run(
            lambda: self._table("fault_injections").insert(record).execute().data
        )
        return FaultInjection.model_validate(rows[0])

    async def list_fault_injections(
        self,
        *,
        service_area_id: str | None = None,
        active_only: bool = False,
    ) -> list[FaultInjection]:
        def query() -> list[dict[str, Any]]:
            builder = self._table("fault_injections").select("*")
            if service_area_id:
                builder = builder.eq("service_area_id", service_area_id)
            if active_only:
                builder = builder.eq("is_active", True)
            return builder.order("started_at", desc=True).limit(200).execute().data

        rows = await self._run(query)
        return [FaultInjection.model_validate(row) for row in rows or []]

    async def clear_fault_injection(
        self, injection_id: str, *, cleared_at: datetime | None = None
    ) -> FaultInjection | None:
        stamp = (cleared_at or datetime.now(timezone.utc)).isoformat()
        rows = await self._run(
            lambda: self._table("fault_injections")
            .update({"is_active": False, "cleared_at": stamp})
            .eq("id", injection_id)
            .execute()
            .data
        )
        return FaultInjection.model_validate(rows[0]) if rows else None

    # -- detection ---------------------------------------------------------
    async def insert_anomalies(self, anomalies: Sequence[Anomaly]) -> list[Anomaly]:
        if not anomalies:
            return []
        payload = [_anomaly_record(anomaly) for anomaly in anomalies]
        rows = await self._run(
            lambda: self._table("anomalies").insert(payload).execute().data
        )
        stored = [_anomaly_from_row(row) for row in rows or []]
        # Row order matches the payload, so the sensor codes survive the trip.
        for anomaly, source in zip(stored, anomalies, strict=False):
            anomaly.sensor_code = source.sensor_code
        return stored

    async def update_anomaly(self, anomaly_id: str, **fields: Any) -> Anomaly | None:
        if not fields:
            return None
        rows = await self._run(
            lambda: self._table("anomalies")
            .update(_jsonable(fields))
            .eq("id", anomaly_id)
            .execute()
            .data
        )
        return _anomaly_from_row(rows[0]) if rows else None

    async def list_anomalies(
        self,
        *,
        service_area_id: str | None = None,
        since: datetime | None = None,
        status: str | None = None,
        fault_event_id: str | None = None,
        limit: int = 200,
    ) -> list[Anomaly]:
        def query() -> list[dict[str, Any]]:
            builder = self._table("anomalies").select("*")
            if service_area_id:
                builder = builder.eq("service_area_id", service_area_id)
            if since is not None:
                builder = builder.gte("detected_at", since.isoformat())
            if status:
                builder = builder.eq("status", status)
            if fault_event_id:
                builder = builder.eq("fault_event_id", fault_event_id)
            return (
                builder.order("detected_at", desc=True).limit(limit).execute().data
            )

        rows = await self._run(query)
        return [_anomaly_from_row(row) for row in rows or []]

    async def create_fault_event(self, event: FaultEvent) -> FaultEvent:
        record = _jsonable(
            {
                "service_area_id": event.service_area_id,
                "asset_id": event.asset_id,
                "fault_type": event.fault_type.value,
                "confidence": event.confidence,
                "detected_at": event.detected_at,
                "severity_score": event.severity_score,
                "households_affected": event.households_affected,
                "evidence": event.evidence,
                "status": event.status,
                "classifier_version": event.classifier_version,
            }
        )
        rows = await self._run(
            lambda: self._table("fault_events").insert(record).execute().data
        )
        return FaultEvent.model_validate(rows[0])

    async def update_fault_event(
        self, fault_event_id: str, **fields: Any
    ) -> FaultEvent | None:
        if not fields:
            return await self.get_fault_event(fault_event_id)
        rows = await self._run(
            lambda: self._table("fault_events")
            .update(_jsonable(fields))
            .eq("id", fault_event_id)
            .execute()
            .data
        )
        return FaultEvent.model_validate(rows[0]) if rows else None

    async def get_fault_event(self, fault_event_id: str) -> FaultEvent | None:
        rows = await self._run(
            lambda: self._table("fault_events")
            .select("*")
            .eq("id", fault_event_id)
            .limit(1)
            .execute()
            .data
        )
        return FaultEvent.model_validate(rows[0]) if rows else None

    async def list_fault_events(
        self,
        *,
        service_area_id: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[FaultEvent]:
        def query() -> list[dict[str, Any]]:
            builder = self._table("fault_events").select("*")
            if service_area_id:
                builder = builder.eq("service_area_id", service_area_id)
            if status:
                builder = builder.eq("status", status)
            if since is not None:
                builder = builder.gte("detected_at", since.isoformat())
            return builder.order("detected_at", desc=True).limit(limit).execute().data

        rows = await self._run(query)
        return [FaultEvent.model_validate(row) for row in rows or []]

    # -- work orders -------------------------------------------------------
    async def create_work_order(self, work_order: WorkOrder) -> WorkOrder:
        record = work_order.model_dump(
            mode="json", exclude={"id", "created_at", "updated_at"}, exclude_none=True
        )
        rows = await self._run(
            lambda: self._table("work_orders").insert(record).execute().data
        )
        return WorkOrder.model_validate(rows[0])

    async def update_work_order(
        self, work_order_id: str, **fields: Any
    ) -> WorkOrder | None:
        if not fields:
            return await self.get_work_order(work_order_id)
        # The `enforce_work_order_transition` trigger is the authority, but
        # checking here turns a Postgres exception into a message naming the
        # states involved -- and costs nothing when the transition is legal.
        if "status" in fields:
            current = await self.get_work_order(work_order_id)
            if current is not None:
                assert_transition(
                    current.status, WorkOrderStatus(fields["status"]), current.wo_code
                )
        rows = await self._run(
            lambda: self._table("work_orders")
            .update(_jsonable({**fields, "updated_at": datetime.now(timezone.utc)}))
            .eq("id", work_order_id)
            .execute()
            .data
        )
        return WorkOrder.model_validate(rows[0]) if rows else None

    async def get_work_order(self, ref: str) -> WorkOrder | None:
        column = "id" if _is_uuid(ref) else "wo_code"
        rows = await self._run(
            lambda: self._table("work_orders")
            .select("*")
            .eq(column, ref)
            .limit(1)
            .execute()
            .data
        )
        return WorkOrder.model_validate(rows[0]) if rows else None

    async def list_work_orders(
        self,
        *,
        service_area_id: str | None = None,
        status: WorkOrderStatus | None = None,
        fault_event_id: str | None = None,
        open_only: bool = False,
        limit: int = 100,
    ) -> list[WorkOrder]:
        def query() -> list[dict[str, Any]]:
            builder = self._table("work_orders").select("*")
            if service_area_id:
                builder = builder.eq("service_area_id", service_area_id)
            if status is not None:
                builder = builder.eq("status", status.value)
            if fault_event_id:
                builder = builder.eq("fault_event_id", fault_event_id)
            if open_only:
                builder = builder.neq("status", WorkOrderStatus.CLOSED.value)
            return builder.order("created_at", desc=True).limit(limit).execute().data

        rows = await self._run(query)
        return [WorkOrder.model_validate(row) for row in rows or []]

    async def next_work_order_code(self) -> str:
        rows = await self._run(
            lambda: self._table("work_orders")
            .select("wo_code")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        # Codes are cosmetic; a collision is resolved by the unique index on
        # wo_code, and the caller retries with the next number.
        last = 0
        if rows:
            suffix = str(rows[0].get("wo_code", "")).rsplit("-", 1)[-1]
            last = int(suffix) if suffix.isdigit() else 0
        return f"WO-{last + 1:03d}"

    # -- assignments and escalations ---------------------------------------
    async def create_assignment(self, assignment: Assignment) -> Assignment:
        record = assignment.model_dump(mode="json", exclude={"id"}, exclude_none=True)
        rows = await self._run(
            lambda: self._table("assignments").insert(record).execute().data
        )
        return Assignment.model_validate(rows[0])

    async def update_assignment(
        self, assignment_id: str, **fields: Any
    ) -> Assignment | None:
        if not fields:
            return None
        rows = await self._run(
            lambda: self._table("assignments")
            .update(_jsonable(fields))
            .eq("id", assignment_id)
            .execute()
            .data
        )
        return Assignment.model_validate(rows[0]) if rows else None

    async def list_assignments(
        self, *, work_order_id: str | None = None, active_only: bool = False
    ) -> list[Assignment]:
        def query() -> list[dict[str, Any]]:
            builder = self._table("assignments").select("*")
            if work_order_id:
                builder = builder.eq("work_order_id", work_order_id)
            if active_only:
                builder = builder.is_("released_at", "null")
            return builder.order("assigned_at").execute().data

        rows = await self._run(query)
        return [Assignment.model_validate(row) for row in rows or []]

    async def create_escalation(self, escalation: Escalation) -> Escalation:
        record = escalation.model_dump(mode="json", exclude={"id"}, exclude_none=True)
        rows = await self._run(
            lambda: self._table("escalations").insert(record).execute().data
        )
        return Escalation.model_validate(rows[0])

    async def update_escalation(
        self, escalation_id: str, **fields: Any
    ) -> Escalation | None:
        if not fields:
            return None
        rows = await self._run(
            lambda: self._table("escalations")
            .update(_jsonable(fields))
            .eq("id", escalation_id)
            .execute()
            .data
        )
        return Escalation.model_validate(rows[0]) if rows else None

    async def list_escalations(
        self, *, work_order_id: str | None = None, unresolved_only: bool = False
    ) -> list[Escalation]:
        def query() -> list[dict[str, Any]]:
            builder = self._table("escalations").select("*")
            if work_order_id:
                builder = builder.eq("work_order_id", work_order_id)
            if unresolved_only:
                builder = builder.is_("resolved_at", "null")
            return builder.order("triggered_at").execute().data

        rows = await self._run(query)
        return [Escalation.model_validate(row) for row in rows or []]

    # -- notifications -----------------------------------------------------
    async def create_notification(self, notification: Notification) -> Notification:
        record = notification.model_dump(
            mode="json", exclude={"id", "created_at"}, exclude_none=True
        )
        rows = await self._run(
            lambda: self._table("notifications").insert(record).execute().data
        )
        return Notification.model_validate(rows[0])

    async def update_notification(
        self, notification_id: str, **fields: Any
    ) -> Notification | None:
        if not fields:
            return None
        rows = await self._run(
            lambda: self._table("notifications")
            .update(_jsonable(fields))
            .eq("id", notification_id)
            .execute()
            .data
        )
        return Notification.model_validate(rows[0]) if rows else None

    async def list_notifications(
        self,
        *,
        work_order_id: str | None = None,
        direction: NotificationDirection | None = None,
        limit: int = 100,
    ) -> list[Notification]:
        def query() -> list[dict[str, Any]]:
            builder = self._table("notifications").select("*")
            if work_order_id:
                builder = builder.eq("work_order_id", work_order_id)
            if direction is not None:
                builder = builder.eq("direction", direction.value)
            return builder.order("created_at", desc=True).limit(limit).execute().data

        rows = await self._run(query)
        return [Notification.model_validate(row) for row in rows or []]

    # -- accountability ----------------------------------------------------
    async def record_decision(self, entry: DecisionEntry) -> DecisionEntry:
        record = entry.model_dump(mode="json", exclude={"id"}, exclude_none=True)
        rows = await self._run(
            lambda: self._table("decision_ledger").insert(record).execute().data
        )
        return DecisionEntry.model_validate(rows[0])

    async def list_decisions(
        self,
        *,
        work_order_id: str | None = None,
        fault_event_id: str | None = None,
        limit: int = 200,
    ) -> list[DecisionEntry]:
        def query() -> list[dict[str, Any]]:
            builder = self._table("decision_ledger").select("*")
            if work_order_id:
                builder = builder.eq("work_order_id", work_order_id)
            if fault_event_id:
                builder = builder.eq("fault_event_id", fault_event_id)
            return builder.order("ts", desc=True).limit(limit).execute().data

        rows = await self._run(query)
        return [DecisionEntry.model_validate(row) for row in rows or []]

    async def get_asset_health(self, asset_id: str) -> AssetHealth | None:
        rows = await self._run(
            lambda: self._table("asset_health")
            .select("*")
            .eq("asset_id", asset_id)
            .limit(1)
            .execute()
            .data
        )
        return AssetHealth.model_validate(rows[0]) if rows else None

    async def upsert_asset_health(self, health: AssetHealth) -> AssetHealth:
        record = health.model_dump(
            mode="json", exclude={"id", "updated_at"}, exclude_none=True
        )
        rows = await self._run(
            lambda: self._table("asset_health")
            .upsert(record, on_conflict="asset_id")
            .execute()
            .data
        )
        return AssetHealth.model_validate(rows[0])

    async def list_asset_health(
        self, *, service_area_id: str | None = None
    ) -> list[AssetHealth]:
        if service_area_id is None:
            rows = await self._run(
                lambda: self._table("asset_health").select("*").execute().data
            )
            return [AssetHealth.model_validate(row) for row in rows or []]
        assets = await self.list_assets(service_area_id)
        asset_ids = [asset.id for asset in assets]
        if not asset_ids:
            return []
        rows = await self._run(
            lambda: self._table("asset_health")
            .select("*")
            .in_("asset_id", asset_ids)
            .execute()
            .data
        )
        return [AssetHealth.model_validate(row) for row in rows or []]

    async def get_vwsc_account(
        self, service_area_id: str, *, fiscal_year: str | None = None
    ) -> VwscAccount | None:
        def query() -> list[dict[str, Any]]:
            builder = (
                self._table("vwsc_accounts")
                .select("*")
                .eq("service_area_id", service_area_id)
            )
            if fiscal_year:
                builder = builder.eq("fiscal_year", fiscal_year)
            return builder.order("fiscal_year", desc=True).limit(1).execute().data

        rows = await self._run(query)
        return VwscAccount.model_validate(rows[0]) if rows else None

    async def update_vwsc_account(
        self, account_id: str, **fields: Any
    ) -> VwscAccount | None:
        if not fields:
            return None
        rows = await self._run(
            lambda: self._table("vwsc_accounts")
            .update(_jsonable({**fields, "updated_at": datetime.now(timezone.utc)}))
            .eq("id", account_id)
            .execute()
            .data
        )
        return VwscAccount.model_validate(rows[0]) if rows else None


def _jsonable(fields: dict[str, Any]) -> dict[str, Any]:
    """Datetimes and enums to what PostgREST accepts over the wire."""
    encoded: dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, datetime):
            encoded[key] = value.isoformat()
        elif isinstance(value, Enum):
            encoded[key] = value.value
        else:
            encoded[key] = value
    return encoded


def _anomaly_record(anomaly: Anomaly) -> dict[str, Any]:
    # `sensor_code` is a convenience for the API and has no column; it is
    # carried in `details` so a stored row can still be read back whole.
    details = dict(anomaly.details)
    if anomaly.sensor_code:
        details.setdefault("sensor_code", anomaly.sensor_code)
    return _jsonable(
        {
            "service_area_id": anomaly.service_area_id,
            "asset_id": anomaly.asset_id,
            "sensor_id": anomaly.sensor_id,
            "detected_at": anomaly.detected_at,
            "window_start": anomaly.window_start,
            "window_end": anomaly.window_end,
            "method": anomaly.method.value,
            "metric": anomaly.metric,
            "observed_value": anomaly.observed_value,
            "baseline_value": anomaly.baseline_value,
            "residual": anomaly.residual,
            "z_score": anomaly.z_score,
            "severity": anomaly.severity,
            "status": anomaly.status,
            "fault_event_id": anomaly.fault_event_id,
            "details": details,
        }
    )


def _anomaly_from_row(row: dict[str, Any]) -> Anomaly:
    anomaly = Anomaly.model_validate(row)
    if anomaly.sensor_code is None:
        anomaly.sensor_code = (anomaly.details or {}).get("sensor_code")
    return anomaly
