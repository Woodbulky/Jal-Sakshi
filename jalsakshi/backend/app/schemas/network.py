"""Wire schemas for service areas, assets, topology and sensors.

These mirror the Supabase tables and are what the operations console consumes.
Field names are stable; breaking changes go into shared/API_CONTRACT.md first.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    SOURCE = "SOURCE"
    PUMP = "PUMP"
    TANK = "TANK"
    VALVE = "VALVE"
    ZONE = "ZONE"
    PIPELINE = "PIPELINE"
    TREATMENT = "TREATMENT"
    METER = "METER"


class AssetStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNDER_REPAIR = "UNDER_REPAIR"
    DECOMMISSIONED = "DECOMMISSIONED"


class SensorType(str, Enum):
    FLOW = "FLOW"
    PRESSURE_UPSTREAM = "PRESSURE_UPSTREAM"
    PRESSURE_TAIL = "PRESSURE_TAIL"
    LEVEL = "LEVEL"
    ENERGY = "ENERGY"
    RUN_HOURS = "RUN_HOURS"
    CHLORINE = "CHLORINE"
    TURBIDITY = "TURBIDITY"
    PH = "PH"


class SensorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"


class QualityFlag(str, Enum):
    GOOD = "GOOD"
    SUSPECT = "SUSPECT"
    STALE = "STALE"
    MISSING = "MISSING"
    FLATLINE = "FLATLINE"
    OUT_OF_RANGE = "OUT_OF_RANGE"


class ServiceArea(BaseModel):
    id: str
    code: str
    name: str
    district: str | None = None
    state: str | None = None
    population: int | None = None
    households: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_demo: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class Asset(BaseModel):
    id: str
    service_area_id: str
    asset_code: str
    asset_type: AssetType
    name: str
    latitude: float | None = None
    longitude: float | None = None
    status: AssetStatus = AssetStatus.OPERATIONAL
    households_served: int = 0
    commissioned_on: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetConnection(BaseModel):
    """Directed topology edge: water flows from_asset_id -> to_asset_id."""

    id: str
    service_area_id: str
    from_asset_id: str
    to_asset_id: str
    connection_type: str = "PIPE"
    diameter_mm: int | None = None
    length_m: float | None = None


class Sensor(BaseModel):
    id: str
    asset_id: str
    sensor_code: str
    sensor_type: SensorType
    unit: str
    sampling_interval_seconds: int = 300
    status: SensorStatus = SensorStatus.ACTIVE
    last_seen_at: datetime | None = None
    expected_min: float | None = None
    expected_max: float | None = None


class SensorReading(BaseModel):
    sensor_id: str
    ts: datetime
    value: float | None = None
    quality_flag: QualityFlag = QualityFlag.GOOD


class SensorWithLatest(Sensor):
    latest: SensorReading | None = None


class NetworkResponse(BaseModel):
    """Everything MapLibre and the console need to draw the live network."""

    service_area: ServiceArea
    nodes: list[Asset]
    edges: list[AssetConnection]
    sensors: list[SensorWithLatest]
    generated_at: datetime


class AssetTelemetry(BaseModel):
    asset: Asset
    sensors: list[Sensor]
    readings: list[SensorReading]
    window_start: datetime | None = None
    window_end: datetime | None = None
