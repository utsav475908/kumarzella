"""Environment-based configuration. Every setting can be overridden with an EL_* environment variable."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EL_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "EdgeLedger"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+psycopg://tj:tj@localhost:5432/tradejournal"
    redis_url: str = "redis://localhost:6379/0"

    # Sessions
    session_cookie_name: str = "el_session"
    csrf_cookie_name: str = "el_csrf"
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False  # must be True in production (HTTPS only)
    secret_key: str = Field(default="dev-insecure-change-me", min_length=16)

    # Rate limiting (requests per window)
    rate_limit_enabled: bool = True
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300
    api_rate_limit: int = 600
    api_rate_window_seconds: int = 60

    # Background jobs. When eager, Celery tasks run inline (tests, single-process dev).
    jobs_eager: bool = True
    large_import_row_threshold: int = 2000

    # Object storage: "local" writes to storage_local_path, "s3" uses an S3-compatible endpoint.
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "./var/storage"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "edgeledger"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"

    max_upload_bytes: int = 10 * 1024 * 1024
    max_import_rows: int = 200_000

    cors_origins: list[str] = ["http://localhost:5173"]

    # Historical market data. "dukascopy" fetches forex 1-minute bid/ask candles from Dukascopy's public datafeed;
    # "none" disables fetching (charts fall back to plotting fills only). dukascopy_base_url may point at an
    # HTTP mirror or a file:// directory laid out like the datafeed (used by tests and offline development).
    marketdata_provider: Literal["dukascopy", "none"] = "dukascopy"
    dukascopy_base_url: str = "https://datafeed.dukascopy.com/datafeed"
    # Dukascopy throttles bursts (HTTP 429) and is sometimes slow to answer; a live check needed a 60 s timeout and
    # several retries. Requests from one process are spaced at least marketdata_min_interval_seconds apart.
    marketdata_timeout_seconds: float = 60.0
    marketdata_retries: int = 6
    marketdata_min_interval_seconds: float = 0.5
    # Requests that need more uncached days than this are queued to the worker instead of fetched inline.
    marketdata_inline_max_days: int = 3
    # A day that failed to download is retried after this many minutes.
    marketdata_error_retry_minutes: int = 30

    # AI coach. Uses the operator's own key for Anthropic (Claude) or OpenAI; without one the coach is switched off and
    # nothing is sent anywhere. "auto" uses Anthropic when its key is set, otherwise OpenAI. ANTHROPIC_API_KEY and
    # OPENAI_API_KEY are accepted too, for native development.
    ai_provider: Literal["auto", "anthropic", "openai"] = "auto"
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("EL_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.5"
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("EL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    anthropic_base_url: str | None = None
    ai_model: str = "claude-opus-5-5"  # Anthropic model
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ai_fallbacks: bool = True  # Anthropic server-side refusal fallbacks (fallbacks: "default")
    ai_max_tokens: int = 8000  # per model call
    ai_max_tool_rounds: int = 6  # model calls that may request tools, per answer
    ai_max_tool_calls: int = 16  # tool executions per answer
    ai_token_budget: int = 250_000  # input + output tokens per answer, across all model calls
    ai_timeout_seconds: float = 120.0
    ai_rate_limit: int = 30  # coach requests per user per window
    ai_rate_window_seconds: int = 3600


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment == "production":
        if s.secret_key.startswith("dev-") or not s.cookie_secure:
            raise RuntimeError("Production requires EL_SECRET_KEY and EL_COOKIE_SECURE=true")
    return s
