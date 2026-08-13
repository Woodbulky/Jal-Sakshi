"""Sensor-evidence verification: the only thing that may close a work order.

A field actor sending "Fixed" on Telegram is an *input*. It starts this
service; it does not end the incident. What ends the incident is the network
reading normally again, on instruments that are themselves trustworthy, for
long enough that a coincidence is not a plausible explanation.

The conditions come from the agent contract:

    flow in expected band
    pressure in expected band
    diurnal pattern restored
    quality restored when relevant
    verification window satisfied

Four outcomes, all first-class:

* ``PASSED``       — every applicable check held. The order may close.
* ``FAILED``       — the network is still not right. The order reopens.
* ``PENDING``      — too soon since restoration to tell. Ask again later.
* ``UNVERIFIABLE`` — the instruments that would settle it cannot be trusted.
                     Saying so is the honest answer; guessing is not.

`UNVERIFIABLE` deliberately does not close anything. A village whose sensor
died during a repair deserves a human looking at it, not an automatic pass.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.analytics.features import Channel, NetworkFeatures
from app.analytics.pipeline import DetectionService
from app.schemas.network import SensorType
from app.schemas.simulation import FaultType
from app.schemas.workorder import (
    VerificationCheck,
    VerificationOutcome,
    VerificationReport,
    WorkOrder,
)

logger = logging.getLogger(__name__)

#: Channels that speak to supply being restored, in the order a human would
#: look at them.
_SUPPLY_TYPES = (
    SensorType.FLOW,
    SensorType.PRESSURE_TAIL,
    SensorType.PRESSURE_UPSTREAM,
    SensorType.LEVEL,
)
#: Quality channels. Only checked when the fault could plausibly affect them --
#: a closed valve does not contaminate water, a burst main can.
_QUALITY_TYPES = (SensorType.TURBIDITY, SensorType.CHLORINE, SensorType.PH)

#: Faults after which water quality is worth re-checking before declaring the
#: village served again.
_QUALITY_RELEVANT = frozenset(
    {
        FaultType.PIPELINE_BURST,
        FaultType.SOURCE_DEPLETION,
        FaultType.THEFT_OR_UNAUTHORISED_TAPPING,
    }
)


class VerificationService:
    """Weighs telemetry against the verification conditions.

    It writes nothing. Deciding what to do with a verdict — close, reopen, or
    mark unverifiable — belongs to the work-order service, so this stays a pure
    reading of the evidence.
    """

    def __init__(
        self,
        detection: DetectionService,
        *,
        window_minutes: float = 20.0,
        band_z: float = 3.5,
        #: A channel may sit this far from its learned day-shape and still count
        #: as restored. Wider than the anomaly threshold on purpose: verifying
        #: is not detecting, and demanding a perfect match would leave real
        #: repairs stuck in VERIFYING forever.
        restored_ratio_low: float = 0.7,
        restored_ratio_high: float = 1.4,
    ) -> None:
        self._detection = detection
        self.window_minutes = window_minutes
        self.band_z = band_z
        self.restored_ratio_low = restored_ratio_low
        self.restored_ratio_high = restored_ratio_high

    async def verify(
        self,
        work_order: WorkOrder,
        *,
        fault_type: FaultType = FaultType.UNKNOWN,
        detected_at: datetime | None = None,
        now: datetime | None = None,
    ) -> VerificationReport:
        now = now or datetime.now(timezone.utc)

        # persist=False: verification observes the network, it does not open
        # incidents. A failed verification reopens the existing work order.
        run = await self._detection.run(now=now, persist=False)
        features = await self._detection.features(now=now)

        checks: list[VerificationCheck] = []
        untrusted = [item.sensor_code for item in run.sensor_health if not item.trusted]

        window = self._window_check(work_order, now)
        checks.append(window)

        relevant = self._relevant_channels(features, work_order, fault_type)
        usable = [channel for channel in relevant if channel.usable]

        for channel in relevant:
            checks.append(self._band_check(channel))
        checks.append(self._pattern_check(usable))

        if fault_type in _QUALITY_RELEVANT:
            for channel in self._quality_channels(features):
                checks.append(self._band_check(channel, quality=True))

        outcome, summary = self._decide(
            checks, relevant=relevant, usable=usable, window=window
        )
        ttwr = None
        if outcome is VerificationOutcome.PASSED and detected_at is not None:
            ttwr = max((now - detected_at).total_seconds() / 60.0, 0.0)

        report = VerificationReport(
            work_order_id=work_order.id,
            outcome=outcome,
            checked_at=now,
            window_minutes=self.window_minutes,
            checks=checks,
            untrusted_sensors=untrusted,
            summary=summary,
            ttwr_minutes=ttwr,
        )
        logger.info(
            "verification %s for %s (%d checks, %d untrusted sensors)",
            outcome.value,
            work_order.wo_code,
            len(checks),
            len(untrusted),
        )
        return report

    # -- individual conditions --------------------------------------------
    def _window_check(self, work_order: WorkOrder, now: datetime) -> VerificationCheck:
        """Enough time since restoration for the reading to mean something."""
        started = (
            work_order.restoration_detected_at
            or work_order.verification_started_at
            or work_order.repair_started_at
        )
        if started is None:
            return VerificationCheck(
                name="verification_window",
                passed=False,
                detail="no restoration timestamp recorded yet",
            )
        elapsed = (now - started).total_seconds() / 60.0
        passed = elapsed >= self.window_minutes
        return VerificationCheck(
            name="verification_window",
            passed=passed,
            detail=(
                f"{elapsed:.0f} of {self.window_minutes:.0f} minutes observed "
                "since restoration"
            ),
            observed=round(elapsed, 1),
            expected_low=self.window_minutes,
        )

    def _band_check(
        self, channel: Channel, *, quality: bool = False
    ) -> VerificationCheck:
        """Is this channel back inside the band its own history predicts?"""
        kind = "quality" if quality else "supply"
        name = f"{channel.sensor_code}_in_band"
        if not channel.trusted:
            return VerificationCheck(
                name=name,
                passed=False,
                detail=f"{kind} channel {channel.sensor_code} is not trusted",
            )
        if channel.value is None:
            return VerificationCheck(
                name=name,
                passed=False,
                detail=f"{kind} channel {channel.sensor_code} has no current reading",
            )
        if channel.ratio is None:
            # No usable baseline ratio (a normally-zero channel). Fall back to
            # the z-score, which the baseline store still provides.
            within = channel.z is None or abs(channel.z) <= self.band_z
            return VerificationCheck(
                name=name,
                passed=within,
                detail=(
                    f"{channel.sensor_code} at {channel.value:.1f}, "
                    f"z={channel.z:.1f}" if channel.z is not None
                    else f"{channel.sensor_code} at {channel.value:.1f}, no baseline"
                ),
                observed=channel.value,
            )
        within = self.restored_ratio_low <= channel.ratio <= self.restored_ratio_high
        return VerificationCheck(
            name=name,
            passed=within,
            detail=(
                f"{channel.sensor_code} at {channel.ratio * 100:.0f}% of its "
                f"usual value for this time of day"
            ),
            observed=round(channel.ratio, 3),
            expected_low=self.restored_ratio_low,
            expected_high=self.restored_ratio_high,
        )

    def _pattern_check(self, usable: list[Channel]) -> VerificationCheck:
        """Diurnal pattern restored: the day-shape, not just the level.

        A channel pinned at a plausible-looking constant is not a restored
        network; it is usually a stuck instrument. Requiring the *set* of
        supply channels to sit near their own time-of-day baseline catches
        that without needing a second model.
        """
        rated = [c for c in usable if c.ratio is not None]
        if not rated:
            return VerificationCheck(
                name="diurnal_pattern",
                passed=False,
                detail="no trusted channel with a usable baseline",
            )
        worst = min(rated, key=lambda c: min(c.ratio, 1 / c.ratio) if c.ratio else 0.0)
        passed = all(
            self.restored_ratio_low <= c.ratio <= self.restored_ratio_high for c in rated
        )
        return VerificationCheck(
            name="diurnal_pattern",
            passed=passed,
            detail=(
                f"{len(rated)} supply channels compared with their learned "
                f"day-shape; furthest is {worst.sensor_code} at "
                f"{worst.ratio * 100:.0f}%"
            ),
            observed=round(worst.ratio, 3),
        )

    # -- channel selection -------------------------------------------------
    def _relevant_channels(
        self,
        features: NetworkFeatures,
        work_order: WorkOrder,
        fault_type: FaultType,
    ) -> list[Channel]:
        """The channels that would show this particular fault as fixed.

        Verifying against every instrument in the village would let an
        unrelated reading block a genuine repair. Verifying against only the
        faulted asset would let a repair that shifted the problem downstream
        pass. So: the faulted asset's own channels, plus the tail-end pressure
        of whichever branch it feeds.
        """
        selected: list[Channel] = []
        seen: set[str] = set()

        def take(channel: Channel | None) -> None:
            if channel is not None and channel.sensor_id not in seen:
                seen.add(channel.sensor_id)
                selected.append(channel)

        if work_order.asset_id:
            for channel in features.channels.values():
                if channel.asset_id == work_order.asset_id and (
                    channel.sensor_type in _SUPPLY_TYPES
                ):
                    take(channel)
            for branch in features.branches:
                if work_order.asset_id in (branch.valve_asset_id, branch.zone_asset_id):
                    take(branch.tail_pressure)
                    take(branch.demand_channel)

        if not selected:
            # No asset, or an asset with no instruments of its own: fall back to
            # the network-wide supply picture rather than verifying nothing.
            take(features.pump_flow)
            take(features.tank_level)
            for branch in features.branches:
                take(branch.tail_pressure)

        if fault_type in (FaultType.PUMP_FAILURE, FaultType.POWER_OUTAGE):
            # These are only really fixed when the motor is drawing again.
            take(features.pump_energy)
            take(features.pump_flow)

        return selected

    def _quality_channels(self, features: NetworkFeatures) -> list[Channel]:
        return [
            channel
            for channel in features.channels.values()
            if channel.sensor_type in _QUALITY_TYPES
        ]

    # -- verdict -----------------------------------------------------------
    def _decide(
        self,
        checks: list[VerificationCheck],
        *,
        relevant: list[Channel],
        usable: list[Channel],
        window: VerificationCheck,
    ) -> tuple[VerificationOutcome, str]:
        if not window.passed:
            return (
                VerificationOutcome.PENDING,
                f"Too early to verify: {window.detail}.",
            )

        if relevant and not usable:
            # Every channel that would settle this is dead. This is exactly the
            # case UNVERIFIABLE exists for.
            codes = ", ".join(c.sensor_code for c in relevant)
            return (
                VerificationOutcome.UNVERIFIABLE,
                (
                    "Restoration cannot be confirmed: the instruments that would "
                    f"show it ({codes}) are not trusted. A human must inspect."
                ),
            )
        if not relevant:
            return (
                VerificationOutcome.UNVERIFIABLE,
                "No instrument covers the repaired asset, so restoration cannot "
                "be confirmed from telemetry.",
            )

        failed = [check for check in checks if not check.passed]
        if not failed:
            return (
                VerificationOutcome.PASSED,
                (
                    f"Restoration confirmed: {len(checks)} checks passed over "
                    f"{self.window_minutes:.0f} minutes of telemetry."
                ),
            )
        reasons = "; ".join(check.detail for check in failed[:3])
        return (
            VerificationOutcome.FAILED,
            f"Restoration not confirmed: {reasons}.",
        )


__all__ = ["VerificationService"]
