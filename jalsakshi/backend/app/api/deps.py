"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.agent.graph import AgentRunner
from app.analytics.pipeline import DetectionService
from app.core.config import Settings, get_settings
from app.integrations.events import EventBus
from app.integrations.n8n import N8nNotifier
from app.services.repository import Repository
from app.simulation.engine import SimulationEngine
from app.workorders.service import WorkOrderService


def get_repository(request: Request) -> Repository:
    repository = getattr(request.app.state, "repository", None)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY.",
        )
    return repository


def get_detection(request: Request) -> DetectionService:
    service = getattr(request.app.state, "detection", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Detection is unavailable because the database is not "
            "configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        )
    return service


def get_simulation(request: Request) -> SimulationEngine:
    engine = getattr(request.app.state, "simulation", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Simulator is unavailable because the database is not "
            "configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        )
    return engine


def get_work_orders(request: Request) -> WorkOrderService:
    service = getattr(request.app.state, "work_orders", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Work orders are unavailable because the database is not "
            "configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        )
    return service


def get_agent(request: Request) -> AgentRunner:
    runner = getattr(request.app.state, "agent", None)
    if runner is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The agent is unavailable because the database is not "
            "configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        )
    return runner


def get_notifier(request: Request) -> N8nNotifier:
    notifier = getattr(request.app.state, "notifier", None)
    if notifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notifications are unavailable because the database is not "
            "configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        )
    return notifier


def get_events(request: Request) -> EventBus:
    """The realtime bus. Always present — it needs no database."""
    bus = getattr(request.app.state, "events", None)
    if bus is None:
        bus = EventBus()
        request.app.state.events = bus
    return bus


RepositoryDep = Annotated[Repository, Depends(get_repository)]
def get_app_settings(request: Request) -> Settings:
    """The settings this app was built with, not the process-wide cache.

    `create_app(settings)` exists so a test — or a second app in one process —
    can run with its own configuration. A route that read `get_settings()`
    directly would quietly ignore that and answer from the environment.
    """
    return getattr(request.app.state, "settings", None) or get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SimulationDep = Annotated[SimulationEngine, Depends(get_simulation)]
DetectionDep = Annotated[DetectionService, Depends(get_detection)]
WorkOrderDep = Annotated[WorkOrderService, Depends(get_work_orders)]
AgentDep = Annotated[AgentRunner, Depends(get_agent)]
NotifierDep = Annotated[N8nNotifier, Depends(get_notifier)]
EventBusDep = Annotated[EventBus, Depends(get_events)]
