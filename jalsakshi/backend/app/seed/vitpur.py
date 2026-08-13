"""Vitpur demo fixture, mirroring the Supabase seed migration.

Vitpur is a fictional demonstration service area only — it is not the project.
This module builds the same topology in memory (deterministic UUIDs) so tests
and local smoke runs need no database.

Source of truth for the real rows: migration `seed_vitpur_demo_service_area`.
"""

from __future__ import annotations

from datetime import date
from uuid import NAMESPACE_URL, uuid5

from app.schemas.network import (
    Asset,
    AssetConnection,
    AssetType,
    Sensor,
    SensorType,
    ServiceArea,
)

SERVICE_AREA_CODE = "demo-vitpur"

_NS = uuid5(NAMESPACE_URL, "https://jal-sakshi.local/demo")


def _uid(*parts: str) -> str:
    return str(uuid5(_NS, "/".join(parts)))


# asset_code, type, name, lat, lon, households, commissioned, metadata
_ASSETS: tuple[tuple[str, AssetType, str, float, float, int, date, dict], ...] = (
    ("SRC-01", AssetType.SOURCE, "Vitpur Borewell Source", 25.4498, 82.6089, 0,
     date(2021, 6, 14), {"yield_lpm": 900, "depth_m": 122}),
    ("PMP-01", AssetType.PUMP, "Vitpur Submersible Pump", 25.4501, 82.6094, 0,
     date(2021, 6, 14), {"rated_kw": 7.5, "rated_flow_lpm": 850, "duty_hours_per_day": 6}),
    ("OHT-01", AssetType.TANK, "Vitpur Overhead Tank", 25.4520, 82.6131, 0,
     date(2021, 7, 2), {"capacity_litres": 75000, "height_m": 15, "staging_m": 12}),
    ("VLV-01", AssetType.VALVE, "Zone A Distribution Valve", 25.4533, 82.6157, 0,
     date(2021, 7, 2), {"diameter_mm": 110, "valve_kind": "sluice"}),
    ("VLV-02", AssetType.VALVE, "Zone B Distribution Valve", 25.4512, 82.6172, 0,
     date(2021, 7, 2), {"diameter_mm": 110, "valve_kind": "sluice"}),
    ("ZONE-A", AssetType.ZONE, "Vitpur Zone A", 25.4547, 82.6188, 212,
     date(2021, 8, 11), {"tail_end": True, "standposts": 14}),
    ("ZONE-B", AssetType.ZONE, "Vitpur Zone B", 25.4496, 82.6205, 168,
     date(2021, 8, 11), {"tail_end": True, "standposts": 11}),
)

# from_code, to_code, connection_type, diameter_mm, length_m
_EDGES: tuple[tuple[str, str, str, int, float], ...] = (
    ("SRC-01", "PMP-01", "RISING_MAIN", 150, 40.0),
    ("PMP-01", "OHT-01", "RISING_MAIN", 150, 380.0),
    ("OHT-01", "VLV-01", "DISTRIBUTION", 110, 260.0),
    ("OHT-01", "VLV-02", "DISTRIBUTION", 110, 310.0),
    ("VLV-01", "ZONE-A", "DISTRIBUTION", 90, 520.0),
    ("VLV-02", "ZONE-B", "DISTRIBUTION", 90, 470.0),
)

# asset_code, short_code, sensor_type, unit, interval_s, expected_min, expected_max
_SENSORS: tuple[tuple[str, str, SensorType, str, int, float, float], ...] = (
    ("SRC-01", "LVL", SensorType.LEVEL, "m", 300, 8.0, 40.0),
    ("PMP-01", "FLW", SensorType.FLOW, "lpm", 300, 0.0, 950.0),
    ("PMP-01", "PRU", SensorType.PRESSURE_UPSTREAM, "bar", 300, 0.0, 4.5),
    ("PMP-01", "ENR", SensorType.ENERGY, "kWh", 300, 0.0, 12.0),
    ("PMP-01", "RNH", SensorType.RUN_HOURS, "h", 300, 0.0, 24.0),
    ("OHT-01", "LVL", SensorType.LEVEL, "m", 300, 0.0, 4.0),
    ("OHT-01", "CHL", SensorType.CHLORINE, "mg/l", 900, 0.0, 1.5),
    ("OHT-01", "TRB", SensorType.TURBIDITY, "NTU", 900, 0.0, 15.0),
    ("OHT-01", "PH", SensorType.PH, "pH", 900, 5.5, 9.5),
    ("VLV-01", "FLW", SensorType.FLOW, "lpm", 300, 0.0, 600.0),
    ("VLV-01", "PRU", SensorType.PRESSURE_UPSTREAM, "bar", 300, 0.0, 3.0),
    ("VLV-02", "FLW", SensorType.FLOW, "lpm", 300, 0.0, 600.0),
    ("VLV-02", "PRU", SensorType.PRESSURE_UPSTREAM, "bar", 300, 0.0, 3.0),
    ("ZONE-A", "FLW", SensorType.FLOW, "lpm", 300, 0.0, 500.0),
    ("ZONE-A", "PRT", SensorType.PRESSURE_TAIL, "bar", 300, 0.0, 2.5),
    ("ZONE-B", "FLW", SensorType.FLOW, "lpm", 300, 0.0, 500.0),
    ("ZONE-B", "PRT", SensorType.PRESSURE_TAIL, "bar", 300, 0.0, 2.5),
)


def build_service_area() -> ServiceArea:
    return ServiceArea(
        id=_uid("service_area", SERVICE_AREA_CODE),
        code=SERVICE_AREA_CODE,
        name="Vitpur",
        district="Fictional District",
        state="Fictional State",
        population=1840,
        households=380,
        latitude=25.4521,
        longitude=82.6134,
        is_demo=True,
        metadata={
            "note": "Fictional demo service area only. Not a real village.",
            "scheme": "JJM-shaped single-village piped water supply",
            "design_supply_lpcd": 55,
        },
    )


def build_assets(service_area_id: str) -> list[Asset]:
    return [
        Asset(
            id=_uid("asset", code),
            service_area_id=service_area_id,
            asset_code=code,
            asset_type=asset_type,
            name=name,
            latitude=lat,
            longitude=lon,
            households_served=households,
            commissioned_on=commissioned,
            metadata=metadata,
        )
        for code, asset_type, name, lat, lon, households, commissioned, metadata in _ASSETS
    ]


def build_connections(service_area_id: str) -> list[AssetConnection]:
    return [
        AssetConnection(
            id=_uid("edge", from_code, to_code),
            service_area_id=service_area_id,
            from_asset_id=_uid("asset", from_code),
            to_asset_id=_uid("asset", to_code),
            connection_type=conn_type,
            diameter_mm=diameter,
            length_m=length,
        )
        for from_code, to_code, conn_type, diameter, length in _EDGES
    ]


def build_sensors() -> list[Sensor]:
    return [
        Sensor(
            id=_uid("sensor", asset_code, short_code),
            asset_id=_uid("asset", asset_code),
            sensor_code=f"SNS-{asset_code}-{short_code}",
            sensor_type=sensor_type,
            unit=unit,
            sampling_interval_seconds=interval,
            expected_min=expected_min,
            expected_max=expected_max,
        )
        for asset_code, short_code, sensor_type, unit, interval, expected_min, expected_max in _SENSORS
    ]


def build_repository_kwargs() -> dict[str, object]:
    """Keyword arguments for `InMemoryRepository` holding the whole of Vitpur."""
    from app.seed.roster import build_vwsc_account  # noqa: PLC0415 -- cycle

    area = build_service_area()
    return {
        "service_areas": [area],
        "assets": build_assets(area.id),
        "connections": build_connections(area.id),
        "sensors": build_sensors(),
        "readings": [],
        # The budget is what makes the approval boundary testable offline.
        "vwsc_accounts": [
            build_vwsc_account(area.id).model_copy(update={"id": _uid("vwsc", area.code)})
        ],
    }
