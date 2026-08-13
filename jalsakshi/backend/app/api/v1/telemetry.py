"""Telemetry read endpoints (shared/API_CONTRACT.md section 2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import RepositoryDep
from app.schemas.network import AssetTelemetry, SensorReading

router = APIRouter(tags=["telemetry"])

DEFAULT_WINDOW_HOURS = 24
MAX_WINDOW_HOURS = 24 * 14


def _window(hours: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(hours=hours), end


@router.get("/assets/{asset_id}/telemetry", response_model=AssetTelemetry)
async def get_asset_telemetry(
    asset_id: str,
    repository: RepositoryDep,
    hours: int = Query(DEFAULT_WINDOW_HOURS, ge=1, le=MAX_WINDOW_HOURS),
    limit: int = Query(2000, ge=1, le=20000),
) -> AssetTelemetry:
    asset = await repository.get_asset(asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"asset '{asset_id}' not found",
        )

    sensors = await repository.list_sensors(asset_id=asset.id)
    start, end = _window(hours)
    readings = await repository.list_readings(
        [sensor.id for sensor in sensors], start=start, end=end, limit=limit
    )

    return AssetTelemetry(
        asset=asset,
        sensors=sensors,
        readings=readings,
        window_start=start,
        window_end=end,
    )


@router.get("/sensors/{sensor_id}/readings", response_model=list[SensorReading])
async def get_sensor_readings(
    sensor_id: str,
    repository: RepositoryDep,
    hours: int = Query(DEFAULT_WINDOW_HOURS, ge=1, le=MAX_WINDOW_HOURS),
    limit: int = Query(1000, ge=1, le=20000),
) -> list[SensorReading]:
    sensor = await repository.get_sensor(sensor_id)
    if sensor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"sensor '{sensor_id}' not found",
        )

    start, end = _window(hours)
    return await repository.list_readings(
        [sensor.id], start=start, end=end, limit=limit
    )
