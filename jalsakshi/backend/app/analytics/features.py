"""Turns a window of readings into the hydraulic picture the rules argue over.

The signature rules do not want raw readings; they want statements like "this
branch is carrying a tenth of its usual flow while the pressure just upstream of
its valve went *up*". This module builds those statements, and only those, so
`signatures.py` stays readable as engineering reasoning rather than indexing.

Structure is taken from the topology, not from Vitpur's asset codes: pump, tank
and source come from asset types, and each branch is a VALVE together with the
ZONE it feeds along an `asset_connections` edge. A second village with three
valves works without a code change.

Two channels are treated specially:

* ``RUN_HOURS`` is a monotonic odometer. Its level says nothing; its *increment*
  across the window says whether the pump is still turning, which is the only
  thing separating a failed pump from a power cut.
* ``ENERGY`` is per-interval kWh, so it is comparable only while the sampling
  interval is constant. The rules therefore lean on its ratio to baseline and on
  "is it essentially zero", never on a raw absolute threshold.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime

from app.analytics.baseline import SensorBaseline
from app.schemas.network import (
    Asset,
    AssetConnection,
    AssetType,
    QualityFlag,
    Sensor,
    SensorReading,
    SensorType,
)

_EPS = 1e-9
#: How many of the newest points make up "now". Enough to shrug off one noisy
#: sample, few enough that a fault developing in the last minute still shows.
_RECENT_POINTS = 3

_USABLE_FLAGS = frozenset({QualityFlag.GOOD, QualityFlag.SUSPECT})


@dataclass
class Channel:
    """One sensor's current standing against its own history."""

    sensor_id: str
    sensor_code: str
    sensor_type: SensorType
    asset_id: str
    asset_code: str
    value: float | None = None
    baseline: float | None = None
    z: float | None = None
    weak_baseline: bool = False
    trusted: bool = True
    #: value / baseline. None when the baseline sits at zero and a ratio would
    #: be meaningless (overnight energy, a normally shut valve).
    ratio: float | None = None
    #: Change across the whole window, per real minute.
    slope_per_minute: float | None = None
    delta: float | None = None
    points: int = 0

    @property
    def usable(self) -> bool:
        return self.value is not None and self.trusted

    def below(self, ratio: float) -> bool:
        return self.usable and self.ratio is not None and self.ratio <= ratio

    def above(self, ratio: float) -> bool:
        return self.usable and self.ratio is not None and self.ratio >= ratio

    def near_zero(self, absolute: float) -> bool:
        return self.usable and abs(self.value or 0.0) <= absolute


@dataclass
class BranchFeatures:
    """A valve and the zone it feeds — the unit a repair crew is sent to."""

    valve_code: str
    valve_asset_id: str
    zone_code: str | None = None
    zone_asset_id: str | None = None
    households: int = 0
    flow: Channel | None = None
    upstream_pressure: Channel | None = None
    zone_flow: Channel | None = None
    tail_pressure: Channel | None = None

    @property
    def demand_channel(self) -> Channel | None:
        """Whichever flow meter actually reports this branch's delivery."""
        return self.zone_flow or self.flow


@dataclass
class NetworkFeatures:
    service_area_id: str
    ts: datetime
    window_start: datetime
    window_end: datetime
    channels: dict[str, Channel] = field(default_factory=dict)
    branches: list[BranchFeatures] = field(default_factory=list)

    pump_flow: Channel | None = None
    pump_pressure: Channel | None = None
    pump_energy: Channel | None = None
    run_hours: Channel | None = None
    tank_level: Channel | None = None
    source_level: Channel | None = None
    turbidity: Channel | None = None
    chlorine: Channel | None = None
    ph: Channel | None = None

    pump_asset_id: str | None = None
    pump_asset_code: str | None = None
    tank_asset_id: str | None = None
    tank_asset_code: str | None = None
    source_asset_id: str | None = None
    source_asset_code: str | None = None

    #: Odometer increment across the window, in hours. > 0 means the motor ran.
    run_hours_delta: float | None = None
    untrusted_sensor_codes: set[str] = field(default_factory=set)

    @property
    def pump_still_turning(self) -> bool | None:
        if self.run_hours_delta is None:
            return None
        return self.run_hours_delta > 1e-4

    def channel(self, sensor_code: str) -> Channel | None:
        return self.channels.get(sensor_code)


def _median_of_recent(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.median(values[-_RECENT_POINTS:])


def _build_channel(
    sensor: Sensor,
    asset: Asset,
    readings: list[SensorReading],
    baseline: SensorBaseline | None,
    *,
    now: datetime,
    trusted: bool,
) -> Channel:
    channel = Channel(
        sensor_id=sensor.id,
        sensor_code=sensor.sensor_code,
        sensor_type=sensor.sensor_type,
        asset_id=asset.id,
        asset_code=asset.asset_code,
        trusted=trusted,
        points=len(readings),
    )
    usable = [r for r in readings if r.value is not None and r.quality_flag in _USABLE_FLAGS]
    if not usable:
        return channel

    values = [float(r.value) for r in usable]  # type: ignore[arg-type]
    channel.value = _median_of_recent(values)

    if len(usable) >= 2:
        span_minutes = (usable[-1].ts - usable[0].ts).total_seconds() / 60.0
        channel.delta = values[-1] - values[0]
        if span_minutes > _EPS:
            channel.slope_per_minute = channel.delta / span_minutes

    if baseline is not None and channel.value is not None:
        scored = baseline.robust_z(channel.value, now)
        if scored is not None:
            channel.z, channel.baseline, channel.weak_baseline = scored
            if abs(channel.baseline) > max(baseline.spread_floor, _EPS):
                channel.ratio = channel.value / channel.baseline
    return channel


def _pick(sensors: list[Sensor], sensor_type: SensorType) -> Sensor | None:
    for sensor in sensors:
        if sensor.sensor_type is sensor_type:
            return sensor
    return None


def build_features(
    *,
    service_area_id: str,
    assets: list[Asset],
    connections: list[AssetConnection],
    sensors: list[Sensor],
    readings_by_sensor: dict[str, list[SensorReading]],
    baselines: dict[str, SensorBaseline],
    untrusted_sensor_ids: set[str],
    now: datetime,
    window_start: datetime,
) -> NetworkFeatures:
    """Assemble the network picture the classifier reasons over."""
    assets_by_id = {asset.id: asset for asset in assets}
    sensors_by_asset: dict[str, list[Sensor]] = {}
    for sensor in sensors:
        sensors_by_asset.setdefault(sensor.asset_id, []).append(sensor)

    features = NetworkFeatures(
        service_area_id=service_area_id,
        ts=now,
        window_start=window_start,
        window_end=now,
    )

    for sensor in sensors:
        asset = assets_by_id.get(sensor.asset_id)
        if asset is None:
            continue
        channel = _build_channel(
            sensor,
            asset,
            readings_by_sensor.get(sensor.id, []),
            baselines.get(sensor.id),
            now=now,
            trusted=sensor.id not in untrusted_sensor_ids,
        )
        features.channels[sensor.sensor_code] = channel
        if not channel.trusted:
            features.untrusted_sensor_codes.add(sensor.sensor_code)

    def channel_for(asset: Asset | None, sensor_type: SensorType) -> Channel | None:
        if asset is None:
            return None
        sensor = _pick(sensors_by_asset.get(asset.id, []), sensor_type)
        return features.channels.get(sensor.sensor_code) if sensor else None

    def first_of(asset_type: AssetType) -> Asset | None:
        for asset in assets:
            if asset.asset_type is asset_type:
                return asset
        return None

    pump = first_of(AssetType.PUMP)
    tank = first_of(AssetType.TANK)
    source = first_of(AssetType.SOURCE)

    if pump is not None:
        features.pump_asset_id, features.pump_asset_code = pump.id, pump.asset_code
        features.pump_flow = channel_for(pump, SensorType.FLOW)
        features.pump_pressure = channel_for(pump, SensorType.PRESSURE_UPSTREAM)
        features.pump_energy = channel_for(pump, SensorType.ENERGY)
        features.run_hours = channel_for(pump, SensorType.RUN_HOURS)
        if features.run_hours is not None:
            features.run_hours_delta = features.run_hours.delta

    if tank is not None:
        features.tank_asset_id, features.tank_asset_code = tank.id, tank.asset_code
        features.tank_level = channel_for(tank, SensorType.LEVEL)
        features.turbidity = channel_for(tank, SensorType.TURBIDITY)
        features.chlorine = channel_for(tank, SensorType.CHLORINE)
        features.ph = channel_for(tank, SensorType.PH)

    if source is not None:
        features.source_asset_id, features.source_asset_code = source.id, source.asset_code
        features.source_level = channel_for(source, SensorType.LEVEL)

    # Branches, read off the topology: valve -> the zone it feeds.
    downstream: dict[str, list[str]] = {}
    for edge in connections:
        downstream.setdefault(edge.from_asset_id, []).append(edge.to_asset_id)

    for asset in assets:
        if asset.asset_type is not AssetType.VALVE:
            continue
        zone = next(
            (
                assets_by_id[target]
                for target in downstream.get(asset.id, [])
                if assets_by_id.get(target)
                and assets_by_id[target].asset_type is AssetType.ZONE
            ),
            None,
        )
        features.branches.append(
            BranchFeatures(
                valve_code=asset.asset_code,
                valve_asset_id=asset.id,
                zone_code=zone.asset_code if zone else None,
                zone_asset_id=zone.id if zone else None,
                households=(zone.households_served if zone else asset.households_served),
                flow=channel_for(asset, SensorType.FLOW),
                upstream_pressure=channel_for(asset, SensorType.PRESSURE_UPSTREAM),
                zone_flow=channel_for(zone, SensorType.FLOW),
                tail_pressure=channel_for(zone, SensorType.PRESSURE_TAIL),
            )
        )
    return features


#: Column order for the optional booster. Appending is safe; reordering is not,
#: because a trained model is indexed by position.
FEATURE_ORDER: tuple[str, ...] = (
    "pump_flow_ratio",
    "pump_flow_z",
    "pump_energy_ratio",
    "pump_energy_value",
    "run_hours_delta",
    "tank_level_ratio",
    "tank_level_slope",
    "source_level_ratio",
    "turbidity_ratio",
    "chlorine_ratio",
    "ph_delta",
    "min_branch_flow_ratio",
    "max_branch_flow_ratio",
    "min_tail_pressure_ratio",
    "max_valve_upstream_ratio",
    "branch_flow_spread",
    "untrusted_sensor_count",
)


def _ratio(channel: Channel | None, default: float = 1.0) -> float:
    if channel is None or not channel.usable or channel.ratio is None:
        return default
    return channel.ratio


def to_vector(features: NetworkFeatures) -> list[float]:
    """Flatten to `FEATURE_ORDER`. Absent channels take a neutral value."""
    branch_flow_ratios = [
        _ratio(branch.demand_channel)
        for branch in features.branches
        if branch.demand_channel is not None and branch.demand_channel.usable
    ] or [1.0]
    tail_ratios = [
        _ratio(branch.tail_pressure)
        for branch in features.branches
        if branch.tail_pressure is not None and branch.tail_pressure.usable
    ] or [1.0]
    upstream_ratios = [
        _ratio(branch.upstream_pressure)
        for branch in features.branches
        if branch.upstream_pressure is not None and branch.upstream_pressure.usable
    ] or [1.0]

    energy_value = (
        features.pump_energy.value
        if features.pump_energy is not None and features.pump_energy.value is not None
        else 0.0
    )
    tank_slope = (
        features.tank_level.slope_per_minute
        if features.tank_level is not None
        and features.tank_level.slope_per_minute is not None
        else 0.0
    )
    ph_delta = 0.0
    if features.ph is not None and features.ph.usable and features.ph.baseline is not None:
        ph_delta = (features.ph.value or 0.0) - features.ph.baseline

    return [
        _ratio(features.pump_flow),
        features.pump_flow.z if features.pump_flow and features.pump_flow.z else 0.0,
        _ratio(features.pump_energy),
        energy_value,
        features.run_hours_delta or 0.0,
        _ratio(features.tank_level),
        tank_slope,
        _ratio(features.source_level),
        _ratio(features.turbidity),
        _ratio(features.chlorine),
        ph_delta,
        min(branch_flow_ratios),
        max(branch_flow_ratios),
        min(tail_ratios),
        max(upstream_ratios),
        max(branch_flow_ratios) - min(branch_flow_ratios),
        float(len(features.untrusted_sensor_codes)),
    ]


__all__ = [
    "BranchFeatures",
    "Channel",
    "FEATURE_ORDER",
    "NetworkFeatures",
    "build_features",
    "to_vector",
]
