"""Simulator control surface.

These endpoints are the judge's console for the demo: start the clock, inject a
fault, repair it. They expose the ground-truth fault label because a human
operator is allowed to know it.

The agent is not. Nothing in the diagnosis path may call `/simulation/*` --
detection has to come from `/assets/{id}/telemetry` like it would in the field.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.deps import SimulationDep
from app.schemas.simulation import (
    BackfillResult,
    FaultInjection,
    InjectFaultRequest,
    SimulationStatus,
)
from app.simulation.engine import (
    DEFAULT_BACKFILL_HOURS,
    DEFAULT_STEP_MINUTES,
    SimulationError,
)

router = APIRouter(prefix="/simulation", tags=["simulation"])


def _bad_request(error: SimulationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.get("/status", response_model=SimulationStatus)
async def simulation_status(engine: SimulationDep) -> SimulationStatus:
    try:
        return await engine.status()
    except SimulationError as error:
        raise _bad_request(error) from error


@router.post("/start", response_model=SimulationStatus)
async def start_simulation(engine: SimulationDep) -> SimulationStatus:
    try:
        await engine.start()
        return await engine.status()
    except SimulationError as error:
        raise _bad_request(error) from error


@router.post("/pause", response_model=SimulationStatus)
async def pause_simulation(engine: SimulationDep) -> SimulationStatus:
    await engine.pause()
    return await engine.status()


@router.post("/tick", response_model=SimulationStatus)
async def tick_once(engine: SimulationDep) -> SimulationStatus:
    """Advance one step by hand. Useful for scripted demos and debugging."""
    try:
        await engine.tick()
        return await engine.status()
    except SimulationError as error:
        raise _bad_request(error) from error


@router.post("/backfill", response_model=BackfillResult)
async def backfill(
    request: Request,
    engine: SimulationDep,
    hours: int = Query(DEFAULT_BACKFILL_HOURS, ge=1, le=336),
    step_minutes: int = Query(DEFAULT_STEP_MINUTES, ge=1, le=60),
) -> BackfillResult:
    """Write a healthy history so detection has a baseline to compare against."""
    try:
        result = await engine.backfill(hours=hours, step_minutes=step_minutes)
    except SimulationError as error:
        raise _bad_request(error) from error

    # The definition of normal just changed. A cached day-shape learned from the
    # replaced history would report the new one as one long anomaly.
    detection = getattr(request.app.state, "detection", None)
    if detection is not None:
        detection.invalidate_baseline()
    return result


@router.post(
    "/inject", response_model=FaultInjection, status_code=status.HTTP_201_CREATED
)
async def inject_fault(
    payload: InjectFaultRequest, engine: SimulationDep
) -> FaultInjection:
    try:
        return await engine.inject(
            fault_type=payload.fault_type,
            asset_ref=payload.asset_id,
            ends_at=payload.ends_at,
            params=payload.params,
        )
    except SimulationError as error:
        raise _bad_request(error) from error


@router.get("/injections", response_model=list[FaultInjection])
async def list_injections(
    engine: SimulationDep, active_only: bool = False
) -> list[FaultInjection]:
    try:
        return await engine.list_injections(active_only=active_only)
    except SimulationError as error:
        raise _bad_request(error) from error


@router.post("/injections/{injection_id}/clear", response_model=FaultInjection)
async def clear_injection(injection_id: str, engine: SimulationDep) -> FaultInjection:
    """'Simulate Repair'. The pipe is fixed; the work order is not closed.

    Clearing the fault only makes the telemetry recover. Closure still requires
    the verification step to observe that recovery and hold.
    """
    try:
        return await engine.clear(injection_id)
    except SimulationError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error


@router.post("/injections/clear-all", response_model=list[FaultInjection])
async def clear_all_injections(engine: SimulationDep) -> list[FaultInjection]:
    try:
        return await engine.clear_all()
    except SimulationError as error:
        raise _bad_request(error) from error
