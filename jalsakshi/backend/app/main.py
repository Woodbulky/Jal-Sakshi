"""JAL-SAKSHI FastAPI application.

An agentic rural-water operations layer: telemetry in, accountable and
sensor-verified restoration out.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import AgentRunner
from app.agent.llm import build_reasoner
from app.agent.tools import AgentTools
from app.analytics.pipeline import DetectionService
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.integrations.events import EventBus
from app.integrations.n8n import N8nNotifier
from app.services.supabase_repository import SupabaseRepository
from app.simulation.engine import SimulationEngine
from app.workorders.service import WorkOrderService
from app.workorders.verification import VerificationService

logger = logging.getLogger("jalsakshi")

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # The realtime bus needs no database and is always available, so a console
    # can connect and be told that nothing is configured.
    if getattr(app.state, "events", None) is None:
        app.state.events = EventBus(
            history=settings.realtime_history,
            queue_size=settings.realtime_queue_size,
        )

    if getattr(app.state, "repository", None) is None:
        if settings.supabase_configured:
            app.state.repository = SupabaseRepository.from_settings(settings)
            logger.info("supabase repository ready", extra={"app_env": settings.app_env})
        else:
            app.state.repository = None
            logger.warning(
                "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are unset; data endpoints "
                "will return 503 until they are configured"
            )

    if getattr(app.state, "detection", None) is None and app.state.repository:
        app.state.detection = DetectionService(app.state.repository, settings)

    # The simulator is idle until /simulation/start; constructing it is cheap
    # and does no I/O.
    if getattr(app.state, "simulation", None) is None and app.state.repository:
        app.state.simulation = SimulationEngine(
            app.state.repository,
            service_area_ref=settings.demo_service_area_id,
            tick_seconds=settings.simulation_tick_seconds,
            time_scale=settings.simulation_time_scale,
        )

    # Work orders and the agent loop. All of this is in-process and does no
    # I/O until something calls it.
    if getattr(app.state, "notifier", None) is None and app.state.repository:
        app.state.notifier = N8nNotifier(app.state.repository, settings)
        if not settings.n8n_webhook_url:
            logger.warning(
                "N8N_WEBHOOK_URL is unset; field messages will be composed and "
                "recorded but not delivered"
            )

    if getattr(app.state, "work_orders", None) is None and app.state.repository:
        app.state.verification = VerificationService(
            app.state.detection,
            window_minutes=settings.verification_window_minutes,
            band_z=settings.detection_z_threshold,
        )
        app.state.work_orders = WorkOrderService(
            app.state.repository,
            verification=app.state.verification,
            notifier=app.state.notifier,
            events=app.state.events,
        )
        app.state.agent = AgentRunner(
            AgentTools(
                app.state.repository, app.state.detection, app.state.work_orders
            ),
            app.state.work_orders,
            reasoner=build_reasoner(settings),
        )
        logger.info(
            "agent loop ready (reasoner=%s)", build_reasoner(settings).name
        )

    # Detection runs off the simulator's tick rather than a clock of its own,
    # so a fault is scored against exactly the sample that revealed it. In a
    # field deployment the same hook hangs off the telemetry ingest.
    detection: DetectionService | None = getattr(app.state, "detection", None)
    engine: SimulationEngine | None = getattr(app.state, "simulation", None)
    bus: EventBus = app.state.events
    if engine is not None:

        async def _after_tick(ts: datetime) -> None:
            await bus.publish("simulation.tick", ts=ts.isoformat())
            if not settings.detection_autorun or detection is None:
                return
            run = await detection.run()
            await bus.publish(
                "detection.run",
                anomalies=len(run.anomalies),
                untrusted_sensors=run.untrusted_sensors,
                fault_type=run.classification.fault_type.value
                if run.classification
                else None,
                confidence=run.classification.confidence
                if run.classification
                else None,
                fault_event_id=run.fault_event.id if run.fault_event else None,
            )

        engine.on_tick = _after_tick

    yield

    engine = getattr(app.state, "simulation", None)
    if engine is not None:
        await engine.pause()
    app.state.simulation = None
    app.state.agent = None
    app.state.work_orders = None
    app.state.verification = None
    app.state.notifier = None
    app.state.detection = None
    app.state.repository = None
    app.state.events = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="JAL-SAKSHI",
        version=VERSION,
        description=(
            "Agentic AI rural-water operations platform. Anomalies become "
            "accountable work orders that close only on sensor evidence."
        ),
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
