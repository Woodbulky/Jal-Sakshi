"""Builds a history the detector can be run against, entirely offline.

The pattern every detection test uses:

    48h of healthy backfill, ending 25 minutes ago
    then five 5-minute samples with the fault physically present
    then detection runs at `now`

The spacing matches the backfill's, which is the invariant the live simulator
also holds (``tick_seconds x time_scale = sampling interval``). Energy is
reported per interval, so mixing spacings would make the energy channel
incomparable with its own baseline — the very channel that separates a failed
pump from a power cut.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas.simulation import FaultType
from app.services.memory_repository import InMemoryRepository
from app.simulation.engine import SimulationEngine

STEP_MINUTES = 5
FAULT_STEPS = 5
FAULT_MINUTES = STEP_MINUTES * FAULT_STEPS


async def build_history(
    repository: InMemoryRepository,
    *,
    fault_type: FaultType | None = None,
    asset_code: str | None = None,
    params: dict[str, Any] | None = None,
    extra_faults: Sequence[dict[str, Any]] = (),
    now: datetime | None = None,
    backfill_hours: int = 48,
) -> datetime:
    """Seed healthy history, then the recent window, and return `now`.

    `extra_faults` takes the same keys and starts alongside the first, which is
    how a network fault and a dead instrument are made to coincide.
    """
    now = now or datetime.now(timezone.utc)
    fault_start = now - timedelta(minutes=FAULT_MINUTES)

    engine = SimulationEngine(
        repository,
        service_area_ref="demo-vitpur",
        tick_seconds=STEP_MINUTES * 60.0,
        time_scale=1.0,
    )
    await engine.backfill(
        hours=backfill_hours, step_minutes=STEP_MINUTES, end=fault_start
    )

    wanted = list(extra_faults)
    if fault_type is not None:
        wanted.insert(
            0,
            {"fault_type": fault_type, "asset_code": asset_code, "params": params},
        )
    for spec in wanted:
        # Created directly rather than through `engine.inject`, which stamps
        # `started_at` with the wall clock; the recent window is in the past.
        await repository.create_fault_injection(
            service_area_id=engine.service_area_id,
            fault_type=spec["fault_type"],
            asset_id=engine.resolve_asset_id(spec.get("asset_code")),
            started_at=fault_start,
            params=spec.get("params") or {},
        )

    for step in range(1, FAULT_STEPS + 1):
        await engine.tick(fault_start + timedelta(minutes=STEP_MINUTES * step))
    return now
