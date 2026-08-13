"""v1 API surface."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    agent,
    assets,
    dashboard,
    detection,
    events,
    health,
    incidents,
    integrations,
    service_areas,
    simulation,
    telemetry,
    work_orders,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(service_areas.router)
api_router.include_router(telemetry.router)
api_router.include_router(detection.router)
api_router.include_router(incidents.router)
api_router.include_router(work_orders.router)
api_router.include_router(agent.router)
api_router.include_router(simulation.router)
api_router.include_router(dashboard.router)
api_router.include_router(assets.router)
api_router.include_router(integrations.router)
api_router.include_router(events.router)
