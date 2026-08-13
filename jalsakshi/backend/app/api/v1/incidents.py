"""Incidents — classified fault events (shared/API_CONTRACT.md section 3).

An incident is what the classifier concluded, carrying the confidence and the
evidence that produced it. It is not ground truth and never claims to be: the
same endpoint will happily report UNKNOWN, which is the correct answer when the
signature is ambiguous.

`POST /incidents/{id}/inject-fault` from the contract is served by
`POST /simulation/inject` instead — injection is an operator action against the
simulator, not an operation on a diagnosed incident, and keeping it there is
what stops the ground-truth label leaking into this surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.analytics.pipeline import DetectionError
from app.api.deps import DetectionDep, RepositoryDep
from app.schemas.detection import Anomaly, FaultEvent

router = APIRouter(tags=["incidents"])


class IncidentDetail(FaultEvent):
    """A fault event together with the anomalies that raised it."""

    anomalies: list[Anomaly] = []


@router.get("/incidents", response_model=list[FaultEvent])
async def list_incidents(
    repository: RepositoryDep,
    detection: DetectionDep,
    hours: int = Query(72, ge=1, le=336),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[FaultEvent]:
    try:
        await detection.load()
    except DetectionError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return await repository.list_fault_events(
        service_area_id=detection.service_area_id,
        status=status_filter,
        since=datetime.now(timezone.utc) - timedelta(hours=hours),
        limit=limit,
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident(incident_id: str, repository: RepositoryDep) -> IncidentDetail:
    event = await repository.get_fault_event(incident_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"incident '{incident_id}' not found",
        )
    anomalies = await repository.list_anomalies(
        service_area_id=event.service_area_id, fault_event_id=event.id, limit=200
    )
    return IncidentDetail(**event.model_dump(), anomalies=anomalies)
