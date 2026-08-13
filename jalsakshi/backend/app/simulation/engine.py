"""Drives the hydraulic model and persists what it produces.

Two modes share one code path:

* ``backfill`` writes a physically consistent history at the real sampling
  interval, so the network has a baseline before the demo starts.
* ``start`` runs a live loop, writing a fresh sample every ``tick_seconds``.

Timestamps are always real wall-clock time -- SLA deadlines and TTWR must stay
honest. Only the hydraulic *integration* is accelerated (``time_scale``), which
moves tank level and meter counters at a pace visible in a 90-second demo.
Flow and pressure are algebraic, so they respond immediately either way.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from app.schemas.network import QualityFlag, SensorReading
from app.schemas.simulation import (
    BackfillResult,
    FaultInjection,
    FaultType,
    SimulationStatus,
)
from app.services.repository import Repository
from app.simulation.faults import resolve_effect
from app.simulation.model import HydraulicState, VitpurModel

logger = logging.getLogger(__name__)

DEFAULT_TICK_SECONDS = 10.0
DEFAULT_TIME_SCALE = 30.0
DEFAULT_BACKFILL_HOURS = 48
DEFAULT_STEP_MINUTES = 5


class SimulationError(RuntimeError):
    """Raised when the simulator is asked to do something it cannot."""


class SimulationEngine:
    def __init__(
        self,
        repository: Repository,
        *,
        service_area_ref: str = "demo-vitpur",
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        time_scale: float = DEFAULT_TIME_SCALE,
        on_tick: "Callable[[datetime], Awaitable[None]] | None" = None,
    ) -> None:
        self._repository = repository
        self._service_area_ref = service_area_ref
        self.tick_seconds = tick_seconds
        self.time_scale = time_scale
        #: Called after each persisted tick. Detection hangs off this; the
        #: simulator itself knows nothing about it, and a failure there must
        #: never stop telemetry being generated.
        self.on_tick = on_tick

        self._model = VitpurModel()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._loaded = False

        self._service_area_id: str = ""
        self._sensor_ids: dict[str, str] = {}  # sensor_code -> id
        self._asset_codes: dict[str, str] = {}  # asset id -> asset_code
        self._asset_ids: dict[str, str] = {}  # asset_code -> id

        self.last_tick_at: datetime | None = None
        self.readings_written = 0

    # -- wiring ------------------------------------------------------------
    async def load(self) -> None:
        """Resolve the demo service area and cache its codes -> ids."""
        if self._loaded:
            return

        area = await self._repository.get_service_area(self._service_area_ref)
        if area is None:
            raise SimulationError(
                f"Service area '{self._service_area_ref}' not found. "
                "Apply the seed migration before starting the simulator."
            )
        self._service_area_id = area.id

        assets = await self._repository.list_assets(area.id)
        self._asset_codes = {a.id: a.asset_code for a in assets}
        self._asset_ids = {a.asset_code: a.id for a in assets}

        sensors = await self._repository.list_sensors(service_area_id=area.id)
        self._sensor_ids = {s.sensor_code: s.id for s in sensors}
        if not self._sensor_ids:
            raise SimulationError(f"Service area '{area.code}' has no sensors.")

        await self._restore_state()
        self._loaded = True

    async def _restore_state(self) -> None:
        """Pick up the tank level and run-hours meter where we left off.

        Without this, a restart would step the tank back to setpoint and the
        odometer back to zero, which would read as an anomaly.
        """
        wanted = {
            code: sensor_id
            for code, sensor_id in self._sensor_ids.items()
            if code in ("SNS-OHT-01-LVL", "SNS-PMP-01-RNH")
        }
        if not wanted:
            return
        latest = await self._repository.latest_readings(list(wanted.values()))
        by_id = {sensor_id: code for code, sensor_id in wanted.items()}
        for sensor_id, reading in latest.items():
            if reading.value is None:
                continue
            code = by_id.get(sensor_id)
            if code == "SNS-OHT-01-LVL":
                self._model.state.oht_level_m = reading.value
            elif code == "SNS-PMP-01-RNH":
                self._model.state.pump_run_hours = reading.value

    def resolve_asset_id(self, ref: str | None) -> str | None:
        """Accept an asset UUID or a code like 'VLV-01'."""
        if not ref:
            return None
        if ref in self._asset_codes:
            return ref
        if ref in self._asset_ids:
            return self._asset_ids[ref]
        raise SimulationError(f"Unknown asset '{ref}' in this service area.")

    @property
    def service_area_id(self) -> str:
        return self._service_area_id

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # -- stepping ----------------------------------------------------------
    async def _active_injections(self, ts: datetime) -> list[FaultInjection]:
        return await self._repository.list_fault_injections(
            service_area_id=self._service_area_id, active_only=True
        )

    def _to_readings(
        self,
        ts: datetime,
        values: dict[str, float | None],
        quality: dict[str, QualityFlag],
    ) -> list[SensorReading]:
        readings: list[SensorReading] = []
        for sensor_code, value in values.items():
            sensor_id = self._sensor_ids.get(sensor_code)
            if sensor_id is None:
                continue  # a sensor the seed does not have; nothing to write
            flag = quality.get(sensor_code, QualityFlag.GOOD)
            if value is None and flag is QualityFlag.GOOD:
                flag = QualityFlag.MISSING
            readings.append(
                SensorReading(
                    sensor_id=sensor_id, ts=ts, value=value, quality_flag=flag
                )
            )
        return readings

    async def tick(self, ts: datetime | None = None) -> int:
        """Generate and persist one sample for every sensor."""
        await self.load()
        ts = ts or datetime.now(timezone.utc)

        async with self._lock:
            injections = await self._active_injections(ts)
            effect = resolve_effect(
                injections,
                ts,
                asset_codes=self._asset_codes,
                time_scale=self.time_scale,
            )
            dt_seconds = self.tick_seconds * self.time_scale
            result = self._model.step(ts, dt_seconds=dt_seconds, effect=effect)
            readings = self._to_readings(ts, result.values, result.quality)

            fault_run_id = injections[0].id if injections else None
            written = await self._repository.insert_readings(
                readings, fault_run_id=fault_run_id
            )

        self.last_tick_at = ts
        self.readings_written += written

        if self.on_tick is not None:
            try:
                await self.on_tick(ts)
            except Exception:  # detection must not break the simulator
                logger.exception("post-tick hook failed")
        return written

    async def backfill(
        self,
        *,
        hours: int = DEFAULT_BACKFILL_HOURS,
        step_minutes: int = DEFAULT_STEP_MINUTES,
        end: datetime | None = None,
    ) -> BackfillResult:
        """Write a healthy history ending at `end` (default: now).

        Runs at real time (no acceleration) so the baseline anomaly detection
        learns from is physically consistent.
        """
        await self.load()
        end = end or datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        step = timedelta(minutes=step_minutes)

        # Settle the tank before recording, so the first hour is not a transient.
        warmup_model = VitpurModel(HydraulicState())
        warm_ts = start - timedelta(hours=6)
        while warm_ts < start:
            warmup_model.step(
                warm_ts, dt_seconds=step.total_seconds(), effect=resolve_effect([], warm_ts)
            )
            warm_ts += step
        self._model = warmup_model

        batch: list[SensorReading] = []
        ts = start
        while ts <= end:
            effect = resolve_effect([], ts)  # history is healthy by construction
            result = self._model.step(ts, dt_seconds=step.total_seconds(), effect=effect)
            batch.extend(self._to_readings(ts, result.values, result.quality))
            ts += step

        written = await self._repository.insert_readings(batch)
        self.readings_written += written
        self.last_tick_at = end
        logger.info(
            "backfilled %s readings over %sh at %s-minute spacing",
            written,
            hours,
            step_minutes,
        )
        return BackfillResult(
            hours=hours,
            step_minutes=step_minutes,
            readings_written=written,
            window_start=start,
            window_end=end,
        )

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        await self.load()
        if self.running:
            return
        self._task = asyncio.create_task(self._loop(), name="jalsakshi-simulation")
        logger.info("simulation started (tick=%ss, time_scale=%s)", self.tick_seconds, self.time_scale)

    async def pause(self) -> None:
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("simulation paused")

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # a bad tick must not kill the simulator
                logger.exception("simulation tick failed")
            await asyncio.sleep(self.tick_seconds)

    # -- faults ------------------------------------------------------------
    async def inject(
        self,
        *,
        fault_type: FaultType,
        asset_ref: str | None = None,
        ends_at: datetime | None = None,
        params: dict | None = None,
    ) -> FaultInjection:
        await self.load()
        asset_id = self.resolve_asset_id(asset_ref)
        injection = await self._repository.create_fault_injection(
            service_area_id=self._service_area_id,
            fault_type=fault_type,
            asset_id=asset_id,
            started_at=datetime.now(timezone.utc),
            ends_at=ends_at,
            params=params or {},
        )
        logger.info(
            "injected %s on %s (run %s)",
            fault_type.value,
            self._asset_codes.get(asset_id or "", "network"),
            injection.id,
        )
        return injection

    async def clear(self, injection_id: str) -> FaultInjection:
        """The demo's 'Simulate Repair': the physical fault goes away.

        Telemetry recovers on the next tick. That recovery is *evidence*, not a
        closure -- only sensor verification may close a work order.
        """
        await self.load()
        cleared = await self._repository.clear_fault_injection(injection_id)
        if cleared is None:
            raise SimulationError(f"No fault injection with id '{injection_id}'.")
        logger.info("cleared fault injection %s", injection_id)
        return cleared

    async def list_injections(self, *, active_only: bool = False) -> list[FaultInjection]:
        await self.load()
        return await self._repository.list_fault_injections(
            service_area_id=self._service_area_id, active_only=active_only
        )

    async def clear_all(self) -> list[FaultInjection]:
        await self.load()
        active = await self._repository.list_fault_injections(
            service_area_id=self._service_area_id, active_only=True
        )
        return [await self.clear(injection.id) for injection in active]

    # -- reporting ---------------------------------------------------------
    async def status(self) -> SimulationStatus:
        await self.load()
        area = await self._repository.get_service_area(self._service_area_ref)
        active = await self._repository.list_fault_injections(
            service_area_id=self._service_area_id, active_only=True
        )
        return SimulationStatus(
            service_area_id=self._service_area_id,
            service_area_code=area.code if area else self._service_area_ref,
            running=self.running,
            tick_seconds=self.tick_seconds,
            time_scale=self.time_scale,
            sensor_count=len(self._sensor_ids),
            last_tick_at=self.last_tick_at,
            readings_written=self.readings_written,
            active_injections=active,
        )


__all__ = [
    "SimulationEngine",
    "SimulationError",
    "DEFAULT_BACKFILL_HOURS",
    "DEFAULT_STEP_MINUTES",
]
