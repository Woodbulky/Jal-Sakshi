"""Liveness and readiness."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.deps import SettingsDep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app_env: str
    database: str
    version: str
    timestamp: datetime
    #: "rules" or "rules+lightgbm" — which classifier is actually loaded.
    classifier: str = "unavailable"
    #: "live" when n8n can be reached for outbound, "recording" when messages
    #: are composed and stored but not delivered.
    messaging: str = "recording"
    realtime_clients: int = 0


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, settings: SettingsDep) -> HealthResponse:
    repository = getattr(request.app.state, "repository", None)
    database = "connected" if repository is not None else "unconfigured"
    detection = getattr(request.app.state, "detection", None)
    if detection is None:
        classifier = "unavailable"
    else:
        classifier = "rules+lightgbm" if detection.booster.available else "rules"
    bus = getattr(request.app.state, "events", None)
    return HealthResponse(
        status="ok" if repository is not None else "degraded",
        app_env=settings.app_env,
        database=database,
        version=request.app.version,
        timestamp=datetime.now(timezone.utc),
        classifier=classifier,
        messaging="live" if settings.n8n_webhook_url else "recording",
        realtime_clients=bus.subscriber_count if bus is not None else 0,
    )
