"""Test fixtures.

The suite runs fully offline against `InMemoryRepository`; no Supabase
credentials are read and no database is contacted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.agent.graph import AgentRunner
from app.agent.llm import StubReasoner
from app.agent.tools import AgentTools
from app.analytics.pipeline import DetectionService
from app.core.config import Settings
from app.main import create_app
from app.schemas.network import SensorReading
from app.seed import vitpur
from app.services.memory_repository import InMemoryRepository
from app.simulation.engine import SimulationEngine
from app.workorders.service import WorkOrderService
from app.workorders.verification import VerificationService


@pytest.fixture
def settings() -> Settings:
    """Configuration for the tests, and nothing from the developer's `.env`.

    `_env_file=None` matters: a machine with `N8N_WEBHOOK_URL` set in its
    environment file must not change what the suite asserts, and a test that
    passed only because someone had a key configured is not a test.
    """
    return Settings(
        _env_file=None,
        app_env="local",
        supabase_url="",
        supabase_service_role_key="",
        cors_origins=["http://localhost:3000"],
    )


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository(**vitpur.build_repository_kwargs())


@pytest.fixture
def repository_with_readings(repository: InMemoryRepository) -> InMemoryRepository:
    """Two hours of five-minute points on the pump flow sensor."""
    sensor = next(s for s in repository.sensors if s.sensor_code == "SNS-PMP-01-FLW")
    now = datetime.now(timezone.utc)
    repository.readings = [
        SensorReading(
            sensor_id=sensor.id,
            ts=now - timedelta(minutes=5 * step),
            value=820.0 - step,
        )
        for step in range(24, -1, -1)
    ]
    return repository


@pytest.fixture
def engine(repository: InMemoryRepository) -> SimulationEngine:
    """Simulator wired to the offline repository, at real time (no speed-up)."""
    return SimulationEngine(
        repository, service_area_ref="demo-vitpur", tick_seconds=300.0, time_scale=1.0
    )


@pytest.fixture
def detection(repository: InMemoryRepository, settings: Settings) -> DetectionService:
    return DetectionService(repository, settings)


@pytest.fixture
def verification(detection: DetectionService) -> VerificationService:
    """Short window so a test does not have to simulate 20 idle minutes."""
    return VerificationService(detection, window_minutes=10.0)


@pytest.fixture
def work_orders(
    repository: InMemoryRepository, verification: VerificationService
) -> WorkOrderService:
    return WorkOrderService(repository, verification=verification)


@pytest.fixture
def tools(
    repository: InMemoryRepository,
    detection: DetectionService,
    work_orders: WorkOrderService,
) -> AgentTools:
    return AgentTools(repository, detection, work_orders)


@pytest.fixture
def agent(tools: AgentTools, work_orders: WorkOrderService) -> AgentRunner:
    """The loop with the deterministic reasoner — no network, no API key."""
    return AgentRunner(tools, work_orders, reasoner=StubReasoner())


@pytest.fixture
def client(settings: Settings, repository: InMemoryRepository) -> TestClient:
    app = create_app(settings)
    app.state.repository = repository
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unconfigured_client(settings: Settings) -> TestClient:
    """App with no repository — as it behaves when Supabase is not configured."""
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
