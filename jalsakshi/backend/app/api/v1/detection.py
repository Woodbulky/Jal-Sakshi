"""Detection surface: sensor health, baselines, anomalies, a manual pass.

Everything here is derived from telemetry. There is deliberately no endpoint
that reveals which fault was injected — that lives under `/simulation/*`, which
is the operator's console, not the agent's.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DetectionDep, RepositoryDep
from app.analytics.pipeline import DetectionError
from app.schemas.detection import (
    Anomaly,
    BaselineBand,
    DetectionRun,
    SensorBaselineProfile,
    SensorHealth,
)

router = APIRouter(tags=["detection"])


def _bad_request(error: DetectionError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("/detection/run", response_model=DetectionRun)
async def run_detection(
    detection: DetectionDep,
    persist: bool = Query(True, description="Write anomalies and the fault event"),
    refresh_baseline: bool = Query(False, description="Relearn the day-shape first"),
) -> DetectionRun:
    """Score the current window now, rather than waiting for the next tick."""
    try:
        return await detection.run(persist=persist, refresh_baseline=refresh_baseline)
    except DetectionError as error:
        raise _bad_request(error) from error


@router.get("/detection/status", response_model=DetectionRun | None)
async def detection_status(detection: DetectionDep) -> DetectionRun | None:
    """The most recent pass, without running another one."""
    return detection.last_run


@router.get("/detection/sensor-health", response_model=list[SensorHealth])
async def sensor_health(detection: DetectionDep) -> list[SensorHealth]:
    """Guardrail 1: which instruments may be believed."""
    try:
        return await detection.sensor_health()
    except DetectionError as error:
        raise _bad_request(error) from error


@router.get(
    "/detection/baseline/{sensor_ref}", response_model=SensorBaselineProfile
)
async def baseline_profile(
    sensor_ref: str, detection: DetectionDep
) -> SensorBaselineProfile:
    """The learned day-shape — the band a chart draws behind the live series."""
    try:
        profile = await detection.baseline_profile(sensor_ref)
    except DetectionError as error:
        raise _bad_request(error) from error
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No baseline for sensor '{sensor_ref}'.",
        )
    return profile


@router.get("/detection/baseline/{sensor_ref}/band", response_model=BaselineBand)
async def baseline_band(
    sensor_ref: str,
    detection: DetectionDep,
    at: datetime | None = Query(None, description="Defaults to now"),
) -> BaselineBand:
    try:
        band = await detection.baseline_band(
            sensor_ref, at or datetime.now(timezone.utc)
        )
    except DetectionError as error:
        raise _bad_request(error) from error
    if band is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No baseline for sensor '{sensor_ref}'.",
        )
    return band


@router.get("/anomalies", response_model=list[Anomaly])
async def list_anomalies(
    repository: RepositoryDep,
    detection: DetectionDep,
    hours: int = Query(24, ge=1, le=336),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
) -> list[Anomaly]:
    try:
        await detection.load()
    except DetectionError as error:
        raise _bad_request(error) from error
    return await repository.list_anomalies(
        service_area_id=detection.service_area_id,
        since=datetime.now(timezone.utc) - timedelta(hours=hours),
        status=status_filter,
        limit=limit,
    )
