"""Signature rules: which fault explains this hydraulic picture?

Each rule is a small argument about physics. A rule has *gates* — conditions
without which the fault is simply not what happened — and weighted supporting
conditions. Its score is the fraction of supporting weight it earns; a failed
gate scores zero. The winning rule's margin over the runner-up then drives
confidence, so two explanations that fit equally well produce a low confidence
and, below the configured threshold, an honest UNKNOWN.

The two rules worth reading closely:

VALVE_CLOSURE
    A closing valve collapses the flow through it *and raises the pressure just
    upstream of it*, because the friction loss disappears along with the flow.
    Detection that only looks for falling pressure misses this fault entirely.
    The rising-upstream term is what separates a shut valve from an empty tank,
    which collapses the same flows but takes the upstream pressure down with it.

PUMP_FAILURE vs POWER_OUTAGE
    Identical in the flow channel: both read zero. They separate only on energy
    and the run-hour odometer. A failed pump is still energised and its meter is
    still counting; a power cut draws nothing and freezes the meter. If the
    energy instrument is untrusted the two rules tie, confidence collapses, and
    the answer is UNKNOWN — which is the correct answer, not a failure.

Nothing here reads `fault_injections`. The rules see only what a field
deployment would see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.analytics.features import BranchFeatures, Channel, NetworkFeatures
from app.schemas.detection import (
    Classification,
    ClassificationCandidate,
    SensorHealth,
)
from app.schemas.simulation import FaultType

if TYPE_CHECKING:  # optional booster; imported for typing only
    from app.analytics.lightgbm_adapter import LightGBMAdapter

CLASSIFIER_VERSION = "signature-rules-v1"

# -- thresholds -------------------------------------------------------------
FLOW_COLLAPSE_RATIO = 0.35  # a branch carrying a third of usual is collapsed
FLOW_DEAD_RATIO = 0.15  # ... and this is not carrying water at all
FLOW_SURGE_RATIO = 1.6  # pump moving this much more than usual is a burst
FLOW_TAPPING_RATIO = 1.25  # a modest, sustained, quiet excess
PRESSURE_COLLAPSE_RATIO = 0.45
PRESSURE_HELD_RATIO = 0.95  # "did not fall" — the valve-closure discriminator
TURBIDITY_SPIKE_RATIO = 2.0
CHLORINE_DROP_RATIO = 0.8
SOURCE_LOW_RATIO = 0.7
ENERGY_DEAD_RATIO = 0.05  # energy this close to zero means no supply
ENERGY_ALIVE_RATIO = 0.15  # ... and this much means the motor is energised


@dataclass
class _Condition:
    weight: float
    holds: bool
    description: str


@dataclass(eq=False)  # identity-hashed, so rules can key a score map
class _Rule:
    fault_type: FaultType
    asset_code: str | None = None
    asset_id: str | None = None
    gates: list[_Condition] = field(default_factory=list)
    conditions: list[_Condition] = field(default_factory=list)
    households: int = 0
    deviation: float = 0.0

    @property
    def gated_out(self) -> bool:
        return any(not gate.holds for gate in self.gates)

    @property
    def score(self) -> float:
        if self.gated_out:
            return 0.0
        total = sum(c.weight for c in self.conditions)
        if total <= 0:
            return 1.0
        earned = sum(c.weight for c in self.conditions if c.holds)
        return earned / total

    def to_candidate(self) -> ClassificationCandidate:
        return ClassificationCandidate(
            fault_type=self.fault_type,
            score=round(self.score, 4),
            asset_code=self.asset_code,
            matched=[c.description for c in self.conditions if c.holds],
            missed=[c.description for c in self.conditions if not c.holds]
            + [f"(required) {g.description}" for g in self.gates if not g.holds],
        )


def _usable(channel: Channel | None) -> bool:
    return channel is not None and channel.usable


def _r(channel: Channel | None) -> float | None:
    """The ratio to baseline, or None when there is nothing to compare with."""
    if channel is None or not channel.usable:
        return None
    return channel.ratio


def _dead(channel: Channel | None, *, ratio: float) -> bool:
    """Essentially zero: either far below baseline, or absolutely negligible."""
    if channel is None or not channel.usable or channel.value is None:
        return False
    if channel.ratio is not None:
        return channel.ratio <= ratio
    return abs(channel.value) <= 1e-6


def _falling(channel: Channel | None) -> bool:
    return (
        channel is not None
        and channel.usable
        and channel.slope_per_minute is not None
        and channel.slope_per_minute < 0
        and (channel.ratio is None or channel.ratio < 0.98)
    )


def _branch_ratio(branch: BranchFeatures) -> float | None:
    return _r(branch.demand_channel)


# -- individual rules -------------------------------------------------------
def _power_outage(features: NetworkFeatures, households: int) -> _Rule:
    pump_flow = features.pump_flow
    energy = features.pump_energy
    rule = _Rule(
        fault_type=FaultType.POWER_OUTAGE,
        asset_code=features.pump_asset_code,
        asset_id=features.pump_asset_id,
        households=households,
        deviation=1.0 - (_r(pump_flow) or 0.0),
    )
    rule.gates = [
        _Condition(1, _dead(pump_flow, ratio=FLOW_DEAD_RATIO), "pump flow at zero"),
    ]
    rule.conditions = [
        _Condition(3, _dead(energy, ratio=ENERGY_DEAD_RATIO), "no energy drawn"),
        _Condition(
            3,
            features.pump_still_turning is False,
            "run-hour meter frozen",
        ),
        _Condition(1, _falling(features.tank_level), "tank draining"),
    ]
    return rule


def _pump_failure(features: NetworkFeatures, households: int) -> _Rule:
    pump_flow = features.pump_flow
    energy = features.pump_energy
    energy_alive = (
        _usable(energy)
        and not _dead(energy, ratio=ENERGY_DEAD_RATIO)
        and (energy.ratio is None or energy.ratio >= ENERGY_ALIVE_RATIO)  # type: ignore[union-attr]
    )
    rule = _Rule(
        fault_type=FaultType.PUMP_FAILURE,
        asset_code=features.pump_asset_code,
        asset_id=features.pump_asset_id,
        households=households,
        deviation=1.0 - (_r(pump_flow) or 0.0),
    )
    rule.gates = [
        _Condition(1, _dead(pump_flow, ratio=FLOW_DEAD_RATIO), "pump flow at zero"),
    ]
    rule.conditions = [
        _Condition(3, bool(energy_alive), "motor still drawing energy"),
        _Condition(3, features.pump_still_turning is True, "run-hour meter still counting"),
        _Condition(1, _falling(features.tank_level), "tank draining"),
    ]
    return rule


def _pipeline_burst(features: NetworkFeatures, households: int) -> _Rule:
    pump_flow = features.pump_flow
    branch_ratios = {
        branch.valve_code: _branch_ratio(branch)
        for branch in features.branches
        if _branch_ratio(branch) is not None
    }
    worst_branch = max(branch_ratios, key=lambda k: branch_ratios[k] or 0.0, default=None)
    branch_surging = (
        worst_branch is not None and (branch_ratios[worst_branch] or 0.0) >= 1.4
    )
    pump_surging = (_r(pump_flow) or 0.0) >= FLOW_SURGE_RATIO

    # Localise: a branch carrying far more than usual is the break. Otherwise
    # the loss is upstream of the valves, on the rising main.
    if branch_surging and worst_branch is not None:
        branch = next(b for b in features.branches if b.valve_code == worst_branch)
        asset_code, asset_id = branch.valve_code, branch.valve_asset_id
        affected = branch.households or households
    else:
        asset_code = features.tank_asset_code or features.pump_asset_code
        asset_id = features.tank_asset_id or features.pump_asset_id
        affected = households

    tail_collapsed = any(
        (_r(branch.tail_pressure) or 1.0) <= PRESSURE_COLLAPSE_RATIO
        for branch in features.branches
    )
    rule = _Rule(
        fault_type=FaultType.PIPELINE_BURST,
        asset_code=asset_code,
        asset_id=asset_id,
        households=affected,
        deviation=max((_r(pump_flow) or 1.0) - 1.0, 0.0),
    )
    rule.gates = [
        _Condition(1, pump_surging or branch_surging, "flow far above normal"),
    ]
    rule.conditions = [
        _Condition(2, tail_collapsed, "tail-end pressure collapsed"),
        _Condition(2, _falling(features.tank_level), "tank draining against the pump"),
        _Condition(
            1.5,
            (_r(features.turbidity) or 1.0) >= TURBIDITY_SPIKE_RATIO,
            "turbidity spike at the break",
        ),
        _Condition(
            1,
            (_r(features.chlorine) or 1.0) <= CHLORINE_DROP_RATIO,
            "chlorine residual diluted",
        ),
        _Condition(
            1,
            (_r(features.pump_energy) or 1.0) >= 1.2,
            "pump drawing more energy",
        ),
    ]
    return rule


def _valve_closure(
    features: NetworkFeatures, branch: BranchFeatures, households: int
) -> _Rule:
    ratio = _branch_ratio(branch)
    upstream = _r(branch.upstream_pressure)
    tail = _r(branch.tail_pressure)

    others = [
        other
        for other in features.branches
        if other.valve_code != branch.valve_code and _branch_ratio(other) is not None
    ]
    others_normal = all((_branch_ratio(other) or 0.0) >= 0.7 for other in others)

    rule = _Rule(
        fault_type=FaultType.VALVE_CLOSURE,
        asset_code=branch.valve_code,
        asset_id=branch.valve_asset_id,
        households=branch.households,
        deviation=1.0 - (ratio or 0.0),
    )
    rule.gates = [
        _Condition(
            1,
            ratio is not None and ratio <= FLOW_COLLAPSE_RATIO,
            f"flow through {branch.valve_code} collapsed",
        ),
    ]
    rule.conditions = [
        # The discriminator. Friction vanishes with the flow, so the pressure
        # upstream of a closing valve rises rather than falls.
        _Condition(
            3,
            upstream is not None and upstream >= PRESSURE_HELD_RATIO,
            "pressure upstream of the valve held or rose",
        ),
        _Condition(
            2,
            tail is not None and tail <= PRESSURE_COLLAPSE_RATIO,
            "zone tail-end pressure collapsed",
        ),
        _Condition(
            1.5,
            bool(others) and others_normal,
            "other branches still supplied",
        ),
        _Condition(
            1,
            (_r(features.pump_flow) or 1.0) <= 1.2,
            "pump flow not elevated (no break drawing water)",
        ),
        _Condition(
            0.5,
            (_r(features.turbidity) or 1.0) < TURBIDITY_SPIKE_RATIO,
            "water quality unchanged",
        ),
    ]
    return rule


def _source_depletion(features: NetworkFeatures, households: int) -> _Rule:
    source = _r(features.source_level)
    branches = [b for b in features.branches if _branch_ratio(b) is not None]
    rule = _Rule(
        fault_type=FaultType.SOURCE_DEPLETION,
        asset_code=features.source_asset_code,
        asset_id=features.source_asset_id,
        households=households,
        deviation=1.0 - (source or 1.0),
    )
    rule.gates = [
        _Condition(
            1,
            source is not None and source <= SOURCE_LOW_RATIO,
            "source level far below normal",
        ),
    ]
    rule.conditions = [
        _Condition(2, (_r(features.pump_flow) or 1.0) <= 0.7, "pump delivering less"),
        _Condition(1.5, _falling(features.tank_level), "tank draining"),
        _Condition(
            1,
            not _dead(features.pump_energy, ratio=ENERGY_DEAD_RATIO),
            "pump still energised",
        ),
        _Condition(
            1,
            bool(branches)
            and all((_branch_ratio(b) or 1.0) <= 0.9 for b in branches),
            "every branch short, not just one",
        ),
    ]
    return rule


def _tapping(features: NetworkFeatures, branch: BranchFeatures) -> _Rule:
    ratio = _branch_ratio(branch)
    tail = _r(branch.tail_pressure)
    rule = _Rule(
        fault_type=FaultType.THEFT_OR_UNAUTHORISED_TAPPING,
        asset_code=branch.valve_code,
        asset_id=branch.valve_asset_id,
        households=branch.households,
        deviation=max((ratio or 1.0) - 1.0, 0.0),
    )
    rule.gates = [
        _Condition(
            1,
            ratio is not None and FLOW_TAPPING_RATIO <= ratio < FLOW_SURGE_RATIO,
            f"{branch.valve_code} carrying a sustained excess",
        ),
    ]
    rule.conditions = [
        # A burst dumps pressure and stirs up sediment; a tap does neither.
        _Condition(2, tail is None or tail >= 0.6, "tail-end pressure broadly held"),
        _Condition(
            1.5,
            (_r(features.turbidity) or 1.0) < TURBIDITY_SPIKE_RATIO,
            "no turbidity spike",
        ),
        _Condition(1, not _falling(features.tank_level), "tank not draining"),
        _Condition(
            1,
            (_r(features.pump_flow) or 1.0) < FLOW_SURGE_RATIO,
            "pump not saturated",
        ),
    ]
    return rule


def _sensor_fault(
    features: NetworkFeatures, unhealthy: list[SensorHealth]
) -> _Rule | None:
    """Only the instrument is broken; the network around it is fine."""
    if not unhealthy:
        return None
    trusted_channels = [c for c in features.channels.values() if c.trusted and c.usable]
    network_quiet = all(
        abs(channel.z) < 3.5 for channel in trusted_channels if channel.z is not None
    )
    first = unhealthy[0]
    rule = _Rule(
        fault_type=FaultType.SENSOR_FAULT,
        asset_code=next(
            (
                c.asset_code
                for c in features.channels.values()
                if c.sensor_code == first.sensor_code
            ),
            None,
        ),
        asset_id=first.asset_id,
        households=0,
        deviation=0.0,
    )
    rule.gates = [_Condition(1, True, "an instrument failed its health check")]
    rule.conditions = [
        _Condition(
            3,
            network_quiet,
            "every trusted channel reads normal",
        ),
        _Condition(
            2,
            bool(trusted_channels),
            "healthy instruments available to corroborate",
        ),
        _Condition(
            1,
            len(unhealthy) <= max(1, len(features.channels) // 3),
            "the failure is confined to a few instruments",
        ),
    ]
    return rule


# -- entry point ------------------------------------------------------------
def classify(
    features: NetworkFeatures,
    *,
    sensor_health: list[SensorHealth],
    total_households: int,
    min_confidence: float = 0.55,
    classifier_version: str = CLASSIFIER_VERSION,
    booster: "LightGBMAdapter | None" = None,
) -> Classification:
    """Weigh every rule and return the best-supported explanation.

    Returns UNKNOWN — deliberately, not as a failure — whenever no rule fits or
    two fit equally well. Acting on a coin-flip diagnosis costs a village its
    only repair crew for the day.

    `booster`, when a trained model is configured, shifts the ranking; the rules
    still supply the asset, the evidence and the wording, so the answer stays
    explainable either way.
    """
    unhealthy = [health for health in sensor_health if not health.trusted]

    rules: list[_Rule] = [
        _power_outage(features, total_households),
        _pump_failure(features, total_households),
        _pipeline_burst(features, total_households),
        _source_depletion(features, total_households),
    ]
    for branch in features.branches:
        rules.append(_valve_closure(features, branch, total_households))
        rules.append(_tapping(features, branch))
    if (sensor_rule := _sensor_fault(features, unhealthy)) is not None:
        rules.append(sensor_rule)

    scores = {rule: rule.score for rule in rules}
    if booster is not None and booster.available:
        best_by_type: dict[FaultType, float] = {}
        for rule in rules:
            best_by_type[rule.fault_type] = max(
                best_by_type.get(rule.fault_type, 0.0), scores[rule]
            )
        blended = booster.blend(best_by_type, features)
        # A rule keeps its share of its class's blended score, so a rule that
        # was gated out stays gated out however confident the model is.
        scores = {
            rule: (
                blended.get(rule.fault_type, 0.0)
                if scores[rule] >= best_by_type.get(rule.fault_type, 0.0) - 1e-9
                else scores[rule]
            )
            if scores[rule] > 0
            else 0.0
            for rule in rules
        }
        classifier_version = f"{classifier_version}{booster.version_suffix}"

    ranked = sorted(rules, key=lambda rule: scores[rule], reverse=True)

    candidates: list[ClassificationCandidate] = []
    for rule in ranked:
        if scores[rule] <= 0 or len(candidates) >= 6:
            break
        candidate = rule.to_candidate()
        candidate.score = round(scores[rule], 4)
        candidates.append(candidate)

    best = ranked[0] if ranked else None
    if best is None or scores[best] <= 0:
        return Classification(
            fault_type=FaultType.UNKNOWN,
            confidence=0.0,
            severity_score=0.0,
            households_affected=0,
            classifier_version=classifier_version,
            summary="Anomalous telemetry that matches no known fault signature.",
            evidence={"candidates": [c.model_dump() for c in candidates]},
            candidates=candidates,
            sensor_health_blocked=bool(unhealthy) and not _has_trusted_anomaly(features),
        )

    runner_up = next(
        (rule for rule in ranked[1:] if rule.fault_type is not best.fault_type), None
    )
    margin = scores[best] - (scores[runner_up] if runner_up else 0.0)
    # A clear winner keeps its score; a near-tie is discounted hard, because a
    # confident wrong dispatch is worse than an honest UNKNOWN.
    confidence = scores[best] * (0.65 + 0.35 * min(1.0, margin / 0.25))

    key_channels = [
        features.pump_flow,
        features.pump_energy,
        features.tank_level,
    ]
    if any(c is not None and c.weak_baseline for c in key_channels):
        confidence *= 0.85

    fault_type = best.fault_type
    if confidence < min_confidence:
        fault_type = FaultType.UNKNOWN

    affected = best.households if fault_type is not FaultType.UNKNOWN else 0
    severity = _severity(best, affected, total_households)

    return Classification(
        fault_type=fault_type,
        confidence=round(min(confidence, 0.99), 4),
        asset_id=best.asset_id if fault_type is not FaultType.UNKNOWN else None,
        asset_code=best.asset_code if fault_type is not FaultType.UNKNOWN else None,
        severity_score=round(severity, 4),
        households_affected=affected,
        classifier_version=classifier_version,
        summary=_summary(fault_type, best, confidence),
        evidence={
            "best_rule": candidates[0].model_dump() if candidates else None,
            "runner_up": next(
                (
                    c.model_dump()
                    for c in candidates[1:]
                    if runner_up is not None and c.fault_type is runner_up.fault_type
                ),
                None,
            ),
            "margin": round(margin, 4),
            "untrusted_sensors": [health.sensor_code for health in unhealthy],
            "channels": _channel_evidence(features),
        },
        candidates=candidates,
        sensor_health_blocked=bool(unhealthy) and not _has_trusted_anomaly(features),
    )


def _has_trusted_anomaly(features: NetworkFeatures, z_threshold: float = 3.5) -> bool:
    return any(
        channel.trusted and channel.z is not None and abs(channel.z) >= z_threshold
        for channel in features.channels.values()
    )


def _severity(rule: _Rule, affected: int, total_households: int) -> float:
    share = (affected / total_households) if total_households else 0.0
    return max(0.0, min(1.0, 0.6 * share + 0.4 * min(1.0, abs(rule.deviation))))


def _summary(fault_type: FaultType, rule: _Rule, confidence: float) -> str:
    if fault_type is FaultType.UNKNOWN:
        return (
            f"Signature is ambiguous (best fit {rule.fault_type.value} at "
            f"{confidence:.0%}); holding at UNKNOWN pending more evidence."
        )
    where = f" at {rule.asset_code}" if rule.asset_code else ""
    matched = [c.description for c in rule.conditions if c.holds]
    because = "; ".join(matched[:3]) if matched else "signature match"
    return f"{fault_type.value}{where} — {because}."


def _channel_evidence(features: NetworkFeatures) -> dict[str, dict[str, float | None]]:
    """Compact per-channel numbers, for the ledger and the operator console."""
    evidence: dict[str, dict[str, float | None]] = {}
    for code, channel in features.channels.items():
        if channel.value is None:
            continue
        evidence[code] = {
            "value": round(channel.value, 4),
            "baseline": round(channel.baseline, 4) if channel.baseline is not None else None,
            "ratio": round(channel.ratio, 4) if channel.ratio is not None else None,
            "z": round(channel.z, 3) if channel.z is not None else None,
        }
    return evidence


__all__ = ["CLASSIFIER_VERSION", "classify"]
