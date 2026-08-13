"""Repository interface for network + telemetry reads.

The API layer depends on this protocol, never on Supabase directly. Production
uses `SupabaseRepository`; tests use `InMemoryRepository`, so the suite runs
offline and never touches a database.

References may be either a UUID or a human code ('demo-vitpur', 'VLV-01'),
because the API contract uses codes in its examples.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class Repository(Protocol):
    async def list_service_areas(self) -> list[ServiceArea]: ...

    async def get_service_area(self, ref: str) -> ServiceArea | None: ...

    async def list_assets(self, service_area_id: str) -> list[Asset]: ...

    async def get_asset(
        self, ref: str, service_area_id: str | None = None
    ) -> Asset | None: ...

    async def list_connections(self, service_area_id: str) -> list[AssetConnection]: ...

    async def list_sensors(
        self,
        *,
        service_area_id: str | None = None,
        asset_id: str | None = None,
    ) -> list[Sensor]: ...

    async def get_sensor(self, ref: str) -> Sensor | None: ...

    async def latest_readings(
        self, sensor_ids: list[str]
    ) -> dict[str, SensorReading]: ...

    async def list_readings(
        self,
        sensor_ids: list[str],
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[SensorReading]: ...

    # -- simulator writes --------------------------------------------------
    async def insert_readings(
        self,
        readings: Sequence[SensorReading],
        *,
        fault_run_id: str | None = None,
    ) -> int:
        """Upsert on (sensor_id, ts) so a backfill can be re-run safely.

        `fault_run_id` is stored for provenance but is never selected back by
        any read path -- it would hand the classifier the answer.
        """
        ...

    async def create_fault_injection(
        self,
        *,
        service_area_id: str,
        fault_type: FaultType,
        asset_id: str | None = None,
        started_at: datetime | None = None,
        ends_at: datetime | None = None,
        params: dict[str, Any] | None = None,
    ) -> FaultInjection: ...

    async def list_fault_injections(
        self,
        *,
        service_area_id: str | None = None,
        active_only: bool = False,
    ) -> list[FaultInjection]: ...

    async def clear_fault_injection(
        self, injection_id: str, *, cleared_at: datetime | None = None
    ) -> FaultInjection | None: ...

    # -- detection ---------------------------------------------------------
    async def insert_anomalies(self, anomalies: Sequence[Anomaly]) -> list[Anomaly]:
        """Persist newly observed anomalies and return them with their ids."""
        ...

    async def update_anomaly(
        self, anomaly_id: str, **fields: Any
    ) -> Anomaly | None: ...

    async def list_anomalies(
        self,
        *,
        service_area_id: str | None = None,
        since: datetime | None = None,
        status: str | None = None,
        fault_event_id: str | None = None,
        limit: int = 200,
    ) -> list[Anomaly]: ...

    async def create_fault_event(self, event: FaultEvent) -> FaultEvent:
        """`event.id` is ignored; the database assigns one."""
        ...

    async def update_fault_event(
        self, fault_event_id: str, **fields: Any
    ) -> FaultEvent | None: ...

    async def get_fault_event(self, fault_event_id: str) -> FaultEvent | None: ...

    async def list_fault_events(
        self,
        *,
        service_area_id: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[FaultEvent]: ...

    # -- work orders -------------------------------------------------------
    async def create_work_order(self, work_order: WorkOrder) -> WorkOrder:
        """`work_order.id` is ignored; the database assigns one."""
        ...

    async def update_work_order(
        self, work_order_id: str, **fields: Any
    ) -> WorkOrder | None:
        """Illegal status transitions are rejected.

        Postgres refuses them in a trigger; the in-memory repository refuses
        them in Python. Both raise so a bug cannot quietly write a work order
        into CLOSED without passing through VERIFYING.
        """
        ...

    async def get_work_order(self, ref: str) -> WorkOrder | None:
        """`ref` may be a UUID or a work-order code ('WO-001')."""
        ...

    async def list_work_orders(
        self,
        *,
        service_area_id: str | None = None,
        status: WorkOrderStatus | None = None,
        fault_event_id: str | None = None,
        open_only: bool = False,
        limit: int = 100,
    ) -> list[WorkOrder]: ...

    async def next_work_order_code(self) -> str:
        """Allocate the next 'WO-nnn'. Codes are unique per deployment."""
        ...

    # -- assignments and escalations ---------------------------------------
    async def create_assignment(self, assignment: Assignment) -> Assignment: ...

    async def update_assignment(
        self, assignment_id: str, **fields: Any
    ) -> Assignment | None: ...

    async def list_assignments(
        self, *, work_order_id: str | None = None, active_only: bool = False
    ) -> list[Assignment]: ...

    async def create_escalation(self, escalation: Escalation) -> Escalation: ...

    async def update_escalation(
        self, escalation_id: str, **fields: Any
    ) -> Escalation | None: ...

    async def list_escalations(
        self, *, work_order_id: str | None = None, unresolved_only: bool = False
    ) -> list[Escalation]: ...

    # -- notifications -----------------------------------------------------
    async def create_notification(self, notification: Notification) -> Notification:
        """Record a message across the n8n edge, in either direction.

        Written before the send is attempted, so a delivery that never
        completes still leaves evidence that it was owed.
        """
        ...

    async def update_notification(
        self, notification_id: str, **fields: Any
    ) -> Notification | None: ...

    async def list_notifications(
        self,
        *,
        work_order_id: str | None = None,
        direction: NotificationDirection | None = None,
        limit: int = 100,
    ) -> list[Notification]: ...

    # -- accountability ----------------------------------------------------
    async def record_decision(self, entry: DecisionEntry) -> DecisionEntry: ...

    async def list_decisions(
        self,
        *,
        work_order_id: str | None = None,
        fault_event_id: str | None = None,
        limit: int = 200,
    ) -> list[DecisionEntry]: ...

    async def get_asset_health(self, asset_id: str) -> AssetHealth | None: ...

    async def upsert_asset_health(self, health: AssetHealth) -> AssetHealth: ...

    async def list_asset_health(
        self, *, service_area_id: str | None = None
    ) -> list[AssetHealth]: ...

    async def get_vwsc_account(
        self, service_area_id: str, *, fiscal_year: str | None = None
    ) -> VwscAccount | None:
        """The committee's budget and the agent's autonomous spend limit."""
        ...

    async def update_vwsc_account(
        self, account_id: str, **fields: Any
    ) -> VwscAccount | None: ...
