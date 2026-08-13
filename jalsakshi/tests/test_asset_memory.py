"""Asset memory: the difference between an agent and an amnesiac ticket queue.

The behaviour under test is the one from the agent contract: when the same
asset keeps failing, stop writing the same repair ticket and say what is
actually wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.simulation import FaultType
from app.services.memory_repository import InMemoryRepository
from app.workorders.memory import AssetMemoryService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def memory(repository: InMemoryRepository) -> AssetMemoryService:
    return AssetMemoryService(repository)


@pytest.fixture
def valve_id(repository: InMemoryRepository) -> str:
    return next(a.id for a in repository.assets if a.asset_code == "VLV-01")


async def test_a_first_failure_has_no_mtbf_and_no_recommendation(
    memory: AssetMemoryService, valve_id: str
) -> None:
    """One failure is an incident, not a pattern. Saying more would be noise."""
    health = await memory.record_failure(
        valve_id,
        fault_type=FaultType.VALVE_CLOSURE,
        detected_at=datetime.now(timezone.utc),
    )

    assert health.failure_count == 1
    assert health.mtbf_hours is None
    assert health.recurring_failure is False
    assert health.recommendation is None


async def test_mtbf_is_the_mean_gap_between_failures(
    memory: AssetMemoryService, valve_id: str
) -> None:
    start = datetime.now(timezone.utc) - timedelta(days=10)
    health = None
    for day in (0, 4, 8):  # gaps of 96h and 96h
        health = await memory.record_failure(
            valve_id,
            fault_type=FaultType.VALVE_CLOSURE,
            detected_at=start + timedelta(days=day),
        )

    assert health.mtbf_hours == pytest.approx(96.0)


async def test_repeated_failures_stop_asking_for_the_same_repair(
    memory: AssetMemoryService, valve_id: str
) -> None:
    """The contract's repeat-failure rule, in the words a committee would use."""
    start = datetime.now(timezone.utc) - timedelta(days=9)
    health = None
    for day in (0, 3, 6):
        health = await memory.record_failure(
            valve_id,
            fault_type=FaultType.VALVE_CLOSURE,
            detected_at=start + timedelta(days=day),
        )

    assert health.failure_count == 3
    assert health.recurring_failure is True
    assert "procedural" in health.recommendation
    # It says how many, over what window, so the claim can be checked.
    assert "3" in health.recommendation
    assert "30 days" in health.recommendation


async def test_the_recommendation_fits_the_fault_class(
    memory: AssetMemoryService, repository: InMemoryRepository
) -> None:
    """A recurring burst and a recurring power cut need different advice."""
    pipe = next(a.id for a in repository.assets if a.asset_code == "VLV-02")
    start = datetime.now(timezone.utc) - timedelta(days=9)
    health = None
    for day in (0, 3, 6):
        health = await memory.record_failure(
            pipe,
            fault_type=FaultType.PIPELINE_BURST,
            detected_at=start + timedelta(days=day),
        )

    assert "section replacement" in health.recommendation
    assert "patch ticket" in health.recommendation


async def test_old_failures_fall_out_of_the_review_window(
    memory: AssetMemoryService, valve_id: str
) -> None:
    """A valve that failed three times last year is not failing repeatedly."""
    now = datetime.now(timezone.utc)
    for days_ago in (400, 300, 200):
        await memory.record_failure(
            valve_id,
            fault_type=FaultType.VALVE_CLOSURE,
            detected_at=now - timedelta(days=days_ago),
        )
    health = await memory.record_failure(
        valve_id, fault_type=FaultType.VALVE_CLOSURE, detected_at=now
    )

    assert health.failure_count == 4
    assert health.recurring_failure is False
    assert health.recommendation is None


async def test_ttwr_is_averaged_across_verified_restorations(
    memory: AssetMemoryService, valve_id: str
) -> None:
    now = datetime.now(timezone.utc)
    await memory.record_failure(
        valve_id, fault_type=FaultType.VALVE_CLOSURE, detected_at=now
    )
    await memory.record_restoration(valve_id, ttwr_minutes=30.0, restored_at=now)
    health = await memory.record_restoration(
        valve_id, ttwr_minutes=90.0, restored_at=now
    )

    assert health.mean_ttwr_minutes == pytest.approx(60.0)
    assert health.last_repair_at is not None


async def test_health_score_falls_with_failures_and_slow_repairs(
    memory: AssetMemoryService, valve_id: str
) -> None:
    now = datetime.now(timezone.utc)
    first = await memory.record_failure(
        valve_id, fault_type=FaultType.VALVE_CLOSURE, detected_at=now
    )
    assert first.health_score < 1.0

    for day in (1, 2, 3):
        await memory.record_failure(
            valve_id,
            fault_type=FaultType.VALVE_CLOSURE,
            detected_at=now + timedelta(days=day),
        )
    worse = await memory.record_restoration(
        valve_id, ttwr_minutes=1440.0, restored_at=now + timedelta(days=3)
    )

    assert worse.health_score < first.health_score
    assert 0.0 <= worse.health_score <= 1.0


async def test_history_stays_bounded(
    memory: AssetMemoryService, valve_id: str
) -> None:
    """An asset with a long life must not grow an unbounded JSON column."""
    now = datetime.now(timezone.utc)
    health = None
    for index in range(40):
        health = await memory.record_failure(
            valve_id,
            fault_type=FaultType.VALVE_CLOSURE,
            detected_at=now + timedelta(hours=index),
        )

    assert len(health.history) == 20
    assert health.failure_count == 40
