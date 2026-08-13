"""Service-area and network endpoints (shared/API_CONTRACT.md sections 1 and 2).

`service_area_id` accepts either the UUID or the code ('demo-vitpur'); the same
holds for asset and sensor references.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.api.deps import RepositoryDep
from app.schemas.network import (
    NetworkResponse,
    SensorWithLatest,
    ServiceArea,
)

router = APIRouter(prefix="/service-areas", tags=["service-areas"])


@router.get("", response_model=list[ServiceArea])
async def list_service_areas(repository: RepositoryDep) -> list[ServiceArea]:
    return await repository.list_service_areas()


@router.get("/{service_area_id}", response_model=ServiceArea)
async def get_service_area(service_area_id: str, repository: RepositoryDep) -> ServiceArea:
    area = await repository.get_service_area(service_area_id)
    if area is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"service area '{service_area_id}' not found",
        )
    return area


@router.get("/{service_area_id}/network", response_model=NetworkResponse)
async def get_network(service_area_id: str, repository: RepositoryDep) -> NetworkResponse:
    """Nodes, edges, sensors and their current values — the map's data source."""
    area = await repository.get_service_area(service_area_id)
    if area is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"service area '{service_area_id}' not found",
        )

    assets = await repository.list_assets(area.id)
    edges = await repository.list_connections(area.id)
    sensors = await repository.list_sensors(service_area_id=area.id)
    latest = await repository.latest_readings([sensor.id for sensor in sensors])

    return NetworkResponse(
        service_area=area,
        nodes=assets,
        edges=edges,
        sensors=[
            SensorWithLatest(**sensor.model_dump(), latest=latest.get(sensor.id))
            for sensor in sensors
        ],
        generated_at=datetime.now(timezone.utc),
    )
