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
