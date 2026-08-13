"""Asset memory: what the system learns from an incident after it closes.

Without this the agent is amnesiac — it would write the same repair ticket for
the same valve every fortnight and never say the useful thing, which is that a
valve failing every fortnight does not have a repair problem, it has a design
or procedure problem.

Two numbers are kept per asset:

* **MTBF** — mean hours between failures. Falls as an asset becomes unreliable.
* **mean TTWR** — mean minutes from detection to verified restoration. Rises as
  an asset becomes hard to reach, hard to diagnose, or short of spares.

`health_score` combines them into one 0..1 figure for the console's map. It is
a summary for humans, not an input to dispatch: routing is decided by the fault
and the households affected, never by a score.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.schemas.simulation import FaultType
from app.schemas.workorder import AssetHealth
from app.services.repository import Repository

logger = logging.getLogger(__name__)

#: Failures at one asset beyond this, inside the review window, stop being
#: individual incidents and start being a pattern.
RECURRENCE_THRESHOLD = 3
#: How far back a repeat failure still counts as part of the same pattern.
RECURRENCE_WINDOW_DAYS = 30.0
#: How many incidents of detail to keep inline on the asset.
HISTORY_LIMIT = 20


class AssetMemoryService:
    def __init__(
        self,
        repository: Repository,
        *,
        recurrence_threshold: int = RECURRENCE_THRESHOLD,
        recurrence_window_days: float = RECURRENCE_WINDOW_DAYS,
    ) -> None:
        self._repository = repository
        self.recurrence_threshold = recurrence_threshold
        self.recurrence_window_days = recurrence_window_days

    async def record_failure(
        self,
        asset_id: str,
        *,
        fault_type: FaultType,
        detected_at: datetime,
        work_order_id: str | None = None,
    ) -> AssetHealth:
        """Called when a fault is confirmed, before anyone is dispatched."""
        health = await self._repository.get_asset_health(asset_id) or AssetHealth(
            asset_id=asset_id
        )
        previous_failure = health.last_failure_at

        history = [
            *health.history,
            {
                "event": "FAILURE",
                "ts": detected_at.isoformat(),
                "fault_type": fault_type.value,
                "work_order_id": work_order_id,
            },
        ][-HISTORY_LIMIT:]

        failure_count = health.failure_count + 1
        mtbf = _updated_mtbf(
            previous_mtbf=health.mtbf_hours,
            failures_before=health.failure_count,
            previous_failure=previous_failure,
            this_failure=detected_at,
        )

        recent = self._recent_failures(history, now=detected_at)
        recurring = recent >= self.recurrence_threshold

        updated = health.model_copy(
            update={
                "failure_count": failure_count,
                "last_failure_at": detected_at,
                "mtbf_hours": mtbf,
                "history": history,
                "recurring_failure": recurring,
                "recommendation": self._recommendation(
                    recurring=recurring,
                    recent=recent,
                    fault_type=fault_type,
                    mtbf_hours=mtbf,
                ),
                "health_score": _health_score(
                    failure_count=failure_count,
                    mtbf_hours=mtbf,
                    mean_ttwr_minutes=health.mean_ttwr_minutes,
                ),
            }
        )
        return await self._repository.upsert_asset_health(updated)

    async def record_restoration(
        self,
        asset_id: str,
        *,
        ttwr_minutes: float,
        restored_at: datetime | None = None,
        work_order_id: str | None = None,
    ) -> AssetHealth:
        """Called only after verification passes. TTWR is a verified number."""
        restored_at = restored_at or datetime.now(timezone.utc)
        health = await self._repository.get_asset_health(asset_id) or AssetHealth(
            asset_id=asset_id
        )

        repairs = sum(1 for row in health.history if row.get("event") == "RESTORED")
        mean_ttwr = _running_mean(health.mean_ttwr_minutes, repairs, ttwr_minutes)

        history = [
            *health.history,
            {
                "event": "RESTORED",
                "ts": restored_at.isoformat(),
                "ttwr_minutes": round(ttwr_minutes, 1),
                "work_order_id": work_order_id,
            },
        ][-HISTORY_LIMIT:]

        updated = health.model_copy(
            update={
                "last_repair_at": restored_at,
                "mean_ttwr_minutes": mean_ttwr,
                "history": history,
                "health_score": _health_score(
                    failure_count=health.failure_count,
                    mtbf_hours=health.mtbf_hours,
                    mean_ttwr_minutes=mean_ttwr,
                ),
            }
        )
        return await self._repository.upsert_asset_health(updated)

    # -- internals ---------------------------------------------------------
    def _recent_failures(self, history: list[dict], *, now: datetime) -> int:
        cutoff_seconds = self.recurrence_window_days * 86400
        count = 0
        for row in history:
            if row.get("event") != "FAILURE":
                continue
            ts = _parse(row.get("ts"))
            if ts is not None and (now - ts).total_seconds() <= cutoff_seconds:
                count += 1
        return count

    def _recommendation(
        self,
        *,
        recurring: bool,
        recent: int,
        fault_type: FaultType,
        mtbf_hours: float | None,
    ) -> str | None:
        """The thing worth saying that another identical ticket would not say."""
        if not recurring:
            return None
        window = int(self.recurrence_window_days)
        base = (
            f"{recent} {fault_type.value} failures at this asset in {window} days"
        )
        if mtbf_hours is not None:
            base += f" (MTBF {mtbf_hours:.0f}h)"
        match fault_type:
            case FaultType.PIPELINE_BURST:
                action = (
                    "repeated bursts point at line condition or pressure regime, "
                    "not at the last repair — commission a section replacement "
                    "review before raising another patch ticket"
                )
            case FaultType.PUMP_FAILURE:
                action = (
                    "recurring pump failures point at the motor, starter or duty "
                    "cycle — order a condition assessment rather than another "
                    "restart"
                )
            case FaultType.VALVE_CLOSURE:
                action = (
                    "a valve that keeps ending up shut is a procedural problem — "
                    "review who operates it and when, and consider locking or "
                    "instrumenting the valve position"
                )
            case FaultType.POWER_OUTAGE:
                action = (
                    "repeated supply loss is a feeder problem — take it up with "
                    "the discom and evaluate backup or solar"
                )
            case FaultType.SENSOR_FAULT:
                action = (
                    "an instrument failing this often is not worth re-servicing — "
                    "plan a replacement"
                )
            case _:
                action = (
                    "review the asset for a design or procedural defect instead of "
                    "repeating the same repair"
                )
        return f"{base}: {action}."


def _updated_mtbf(
    *,
    previous_mtbf: float | None,
    failures_before: int,
    previous_failure: datetime | None,
    this_failure: datetime,
) -> float | None:
    """Mean hours between failures. Undefined until there are two."""
    if previous_failure is None:
        return previous_mtbf
    gap_hours = max((this_failure - previous_failure).total_seconds() / 3600.0, 0.0)
    # `failures_before - 1` gaps have been averaged so far.
    gaps_before = max(failures_before - 1, 0)
    return _running_mean(previous_mtbf, gaps_before, gap_hours)


def _running_mean(current: float | None, count: int, value: float) -> float:
    if current is None or count <= 0:
        return value
    return (current * count + value) / (count + 1)


def _health_score(
    *,
    failure_count: int,
    mtbf_hours: float | None,
    mean_ttwr_minutes: float | None,
) -> float:
    """0..1, where 1 is an asset that has never given trouble.

    Deliberately blunt: three linear penalties a committee member can follow,
    not a fitted curve nobody can argue with.
    """
    score = 1.0
    score -= min(failure_count * 0.08, 0.4)
    if mtbf_hours is not None and mtbf_hours > 0:
        # Under a week between failures is where an asset starts being a
        # liability rather than an inconvenience.
        score -= min(max((168.0 - mtbf_hours) / 168.0, 0.0) * 0.4, 0.4)
    if mean_ttwr_minutes is not None:
        # Beyond a day to restore, the asset is effectively unsupported.
        score -= min(mean_ttwr_minutes / 1440.0, 1.0) * 0.2
    return round(max(0.0, min(1.0, score)), 3)


def _parse(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


__all__ = ["AssetMemoryService", "RECURRENCE_THRESHOLD", "RECURRENCE_WINDOW_DAYS"]
