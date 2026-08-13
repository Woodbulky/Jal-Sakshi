"""Application configuration.

Values come from the environment (see `.env.example`). The database is Supabase
and only Supabase; there is no local database and no SQLite fallback.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    api_prefix: str = "/api/v1"
    # NoDecode: read CORS_ORIGINS as a plain comma-separated string rather than
    # letting pydantic-settings try to JSON-decode it out of the env file.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    demo_service_area_id: str = "demo-vitpur"

    #: Wall-clock seconds between live simulator samples.
    simulation_tick_seconds: float = 10.0
    #: Hydraulic integration runs this much faster than real time so tank level
    #: and meter counters move visibly in a 90-second demo. Timestamps stay real.
    simulation_time_scale: float = 30.0

    # -- detection ---------------------------------------------------------
    #: How much history the diurnal baseline is learned from.
    detection_baseline_hours: int = 48
    #: Recomputing the baseline is the expensive query, so it is cached.
    detection_baseline_refresh_seconds: float = 900.0
    #: Ignore the newest slice when learning: a fault developing right now must
    #: not be absorbed into the definition of "normal".
    detection_baseline_exclude_recent_minutes: float = 45.0
    #: Width of a time-of-day bucket in the learned day-shape.
    detection_bucket_minutes: int = 30
    #: Below this many samples a bucket is widened, then declared weak.
    detection_min_bucket_samples: int = 6

    #: Readings this recent are "now" for the detector.
    detection_window_minutes: float = 15.0
    #: Robust |z| at which a channel counts as anomalous.
    detection_z_threshold: float = 3.5
    #: Below this the classifier must answer UNKNOWN (guardrail 2).
    detection_min_confidence: float = 0.55
    #: A channel that keeps deviating updates its anomaly instead of adding one.
    detection_anomaly_dedupe_minutes: float = 10.0
    #: Run detection automatically after every simulator tick.
    detection_autorun: bool = True
    #: A sensor silent for longer than this multiple of its sampling interval
    #: is stale rather than merely quiet.
    detection_stale_interval_multiplier: float = 3.0
    #: Identical consecutive readings needed before an instrument is flatlined.
    detection_flatline_points: int = 6

    # -- work orders and verification --------------------------------------
    #: Telemetry must read normal for this long after a reported repair before
    #: restoration is confirmed. Short enough for a live demo, long enough that
    #: one lucky sample cannot close an incident.
    verification_window_minutes: float = 20.0
    #: Failures at one asset inside the review window before the agent stops
    #: writing repair tickets and recommends a design or procedural review.
    asset_recurrence_threshold: int = 3
    asset_recurrence_window_days: float = 30.0

    #: Optional trained booster. Absent -> the signature rules run alone.
    lightgbm_model_path: str = ""
    #: Weight given to the booster when one is loaded; the rules keep the rest.
    lightgbm_blend_weight: float = 0.5

    # Groq is OpenAI-wire-compatible, so it is reached through a base URL rather
    # than a bespoke client.
    llm_provider: Literal["none", "groq", "anthropic", "google", "openai"] = "none"
    llm_model: str = "llama-3.3-70b-versatile"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 30.0

    # -- n8n / Telegram ----------------------------------------------------
    #: Blank disables delivery. Messages are still composed and recorded, so
    #: the console shows what a field actor would have been sent.
    n8n_webhook_url: str = ""
    #: Signs the outbound body (HMAC-SHA256) so n8n can reject impostors.
    n8n_webhook_secret: str = ""
    n8n_timeout_seconds: float = 10.0
    #: Presented by n8n on inbound callbacks. Blank refuses every callback:
    #: an unauthenticated route that can move a work order is not a default.
    inbound_callback_secret: str = ""
    #: Where this deployment is reachable, so outbound payloads can carry the
    #: callback URL n8n replies to.
    public_base_url: str = ""

    # -- realtime ----------------------------------------------------------
    #: Events retained for replay to a console that reconnects.
    realtime_history: int = 200
    #: Per-client buffer. A console that stops draining loses its oldest
    #: events rather than slowing the agent down.
    realtime_queue_size: int = 100
    #: Comment frames keep proxies from closing an idle stream.
    realtime_heartbeat_seconds: float = 15.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def llm_configured(self) -> bool:
        """False falls back to the deterministic stub reasoner."""
        return self.llm_provider != "none" and bool(self.llm_api_key)

    @property
    def resolved_llm_base_url(self) -> str:
        if self.llm_base_url:
            return self.llm_base_url
        if self.llm_provider == "groq":
            return "https://api.groq.com/openai/v1"
        return ""

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
