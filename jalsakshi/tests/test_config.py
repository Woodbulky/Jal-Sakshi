from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings


def test_cors_origins_parse_from_a_comma_separated_env_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")

    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_parse_from_a_dotenv_file(tmp_path: Path) -> None:
    """Regression: pydantic-settings used to JSON-decode this and blow up."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000\n", encoding="utf-8"
    )

    settings = Settings(_env_file=env_file)

    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_supabase_configured_requires_the_service_role_key() -> None:
    assert not Settings(
        supabase_url="https://x.supabase.co", supabase_service_role_key=""
    ).supabase_configured
    assert Settings(
        supabase_url="https://x.supabase.co", supabase_service_role_key="secret"
    ).supabase_configured


def test_a_tick_advances_simulated_time_by_the_backfill_step() -> None:
    """`tick_seconds * time_scale` must equal the baseline's sampling step.

    Energy is reported as kWh *per interval*, so it is only comparable while
    that interval is constant. Raising the tick from 10s to 15s without
    dropping the time scale from 30 to 20 stretched every sample to 450s of
    simulated time, inflated each energy reading by half against a baseline
    learned at 300s, and detection opened a 26-sigma incident on a network
    where nothing was wrong. It was right to; the configuration was lying to
    it.

    This guards the product, not either factor: tune the tick for CPU and the
    scale for pace, but keep them multiplying to the backfill step.
    """
    from app.simulation.engine import DEFAULT_STEP_MINUTES

    settings = Settings(_env_file=None, supabase_url="", supabase_service_role_key="")

    assert (
        settings.simulation_tick_seconds * settings.simulation_time_scale
        == DEFAULT_STEP_MINUTES * 60
    )
