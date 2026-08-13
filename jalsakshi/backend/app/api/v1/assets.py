"""Asset health.

What the system remembers about a piece of infrastructure across incidents:
how often it fails, how long it takes to restore, and whether repeating the
same repair is still the right answer. The agent writes this record in its
`remember` node; the console reads it here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import RepositoryDep
from app.schemas.detection import FaultEvent
from app.schemas.network import Asset
from app.schemas.workorder import AssetHealth, WorkOrder

router = APIRouter(tags=["assets"])


class AssetHealthDetail(BaseModel):
    """An asset's health record with the incidents that produced it."""

    asset: Asset
    health: AssetHealth | None = None
    incidents: list[FaultEvent] = Field(default_factory=list)
    work_orders: list[WorkOrder] = Field(default_factory=list)


@router.get("/assets/{asset_ref}/health", response_model=AssetHealthDetail)
async def asset_health(
    asset_ref: str,
    repository: RepositoryDep,
    days: int = Query(365, ge=1, le=1825, description="Incident history window"),
) -> AssetHealthDetail:
    asset = await repository.get_asset(asset_ref)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"asset '{asset_ref}' not found",
        )

    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = await repository.list_fault_events(
        service_area_id=asset.service_area_id, since=since, limit=500
    )
    orders = await repository.list_work_orders(
        service_area_id=asset.service_area_id, limit=500
    )

    return AssetHealthDetail(
        asset=asset,
        health=await repository.get_asset_health(asset.id),
        incidents=[event for event in events if event.asset_id == asset.id],
        work_orders=[order for order in orders if order.asset_id == asset.id],
    )


@router.get("/asset-health", response_model=list[AssetHealth])
async def list_asset_health(
    repository: RepositoryDep, service_area_id: str | None = None
) -> list[AssetHealth]:
    """The fleet view: every asset the system has an opinion about."""
    return await repository.list_asset_health(service_area_id=service_area_id)
