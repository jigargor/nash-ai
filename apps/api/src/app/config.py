from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.url import is_railway_managed_postgres_host


def _env_files() -> tuple[str, ...]:
    """Resolve .env paths relative to this package (not the process cwd).

    Supports repo-root `.env.local` (monorepo) and `apps/api/.env` without
    requiring uvicorn to be started from a specific directory.
    Later files override earlier ones.
    """
    here = Path(__file__).resolve().parent  # .../apps/api/src/app
    apps_api = here.parent.parent  # .../apps/api
    repo_root = here.parent.parent.parent.parent  # repo root (parent of apps/)
    ordered = [
        apps_api / ".env",
        apps_api / ".env.local",
        repo_root / ".env",
        repo_root / ".env.local",
    ]
    found = tuple(str(p) for p in ordered if p.is_file())
    return found if found else (".env",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_app_id: str
    github_webhook_secret: str
    APP_PRIVATE_KEY_PEM: str | None = None
    APP_PRIVATE_KEY_PEM_path: Path = Path("private-key.pem")
    # Dashboard OAuth (used by Next.js BFF). Optional on the API/worker: workers do not
    # exchange user OAuth codes; omit on Railway worker services if unset.
    github_client_id: str | None = None
    github_client_secret: str | None = None
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    db_command_timeout_seconds: int = 30
    # asyncpg connect establishment timeout (avoid long hangs before pool timeout / LB 502).
    db_connect_timeout_seconds: int = 15
    db_statement_timeout_ms: int = 30_000
    redis_url: str = "redis://localhost:6379"
    fernet_key: str
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_default_model: str = "claude-sonnet-4-5"
    openai_default_model: str = "gpt-5.5"
    gemini_default_model: str = "gemini-2.5-pro"
    environment: str = "development"
    log_webhook_payloads: bool = False
    admin_retry_api_key: str | None = None
    api_access_key: str | None = None
    dashboard_user_jwt_secret: str | None = None
    dashboard_user_jwt_audience: str = "dashboard-api"
    dashboard_user_jwt_issuer: str = "nash-web-dashboard"
    terms_version: str = "2026-04-29"
    enable_reviews: bool = True
    reviews_per_hour_limit: int = 30
    daily_token_budget_per_installation: int = 10_000_000
    sentry_dsn: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    confident_api_key: str | None = None
    deepeval_tracing_enabled: bool = False
    observability_enabled: bool = False
    observability_sinks: str = "disabled"
    observability_payload_mode: str = "metadata_only"
    observability_sample_rate: float = 1.0
    observability_emit_tool_payload_hashes: bool = True
    observability_max_metadata_bytes: int = 8192
    observability_max_events_per_review: int = 500
    web_app_url: str | None = None
    snapshot_retention_days: int = 30
    snapshot_archive_batch_size: int = 100
    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_region: str = "auto"
    r2_snapshot_prefix: str = "review-snapshots"
    turnstile_secret_key: str | None = None
    turnstile_siteverify_url: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    # When R2 archive is enabled: UTC instant you last rotated R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY.
    r2_credentials_rotated_at: datetime | None = None
    # Max age for those keys before startup fails (production vs non-production).
    r2_access_key_max_age_days_production: int = 30
    r2_access_key_max_age_days_development: int = 90

    @field_validator("github_client_id", "github_client_secret", mode="before")
    @classmethod
    def strip_optional_github_oauth(cls, v: object) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    @field_validator("github_app_id", mode="before")
    @classmethod
    def strip_github_app_id(cls, v: object) -> str:
        if v is None:
            raise ValueError("GITHUB_APP_ID is required")
        return str(v).strip()

    @field_validator("APP_PRIVATE_KEY_PEM_path", mode="after")
    @classmethod
    def resolve_APP_PRIVATE_KEY_PEM_path(cls, v: Path) -> Path:
        """Paths from .env are relative to apps/api (not the process cwd).

        Workers are often started from apps/api/src; without this, ./private-key.pem
        resolves to apps/api/src/private-key.pem and GitHub JWT auth returns 401.
        """
        if v.is_absolute():
            return v.resolve()
        apps_api = Path(__file__).resolve().parent.parent.parent
        return (apps_api / v).resolve()

    @field_validator("APP_PRIVATE_KEY_PEM", mode="before")
    @classmethod
    def strip_APP_PRIVATE_KEY_PEM(cls, v: object) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    @field_validator("r2_credentials_rotated_at", mode="before")
    @classmethod
    def parse_r2_credentials_rotated_at(cls, v: object) -> datetime | None:
        from app.storage.r2_rotation import parse_r2_credentials_rotated_at

        return parse_r2_credentials_rotated_at(v)

    @field_validator("web_app_url", mode="before")
    @classmethod
    def normalize_web_app_url(cls, v: object) -> str | None:
        if v is None:
            return None
        text = str(v).strip().rstrip("/")
        return text or None

    @field_validator("observability_payload_mode", mode="before")
    @classmethod
    def validate_observability_payload_mode(cls, v: object) -> str:
        value = str(v or "metadata_only").strip().lower()
        allowed = {
            "metadata_only",
            "hashed_payloads",
            "redacted_payloads",
            "raw_debug_local_only",
        }
        if value not in allowed:
            raise ValueError(f"OBSERVABILITY_PAYLOAD_MODE must be one of: {sorted(allowed)}")
        return value

    @field_validator("observability_sample_rate", mode="after")
    @classmethod
    def validate_observability_sample_rate(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("OBSERVABILITY_SAMPLE_RATE must be between 0 and 1")
        return v

    @field_validator("fernet_key", mode="after")
    @classmethod
    def validate_fernet_key(cls, v: str) -> str:
        try:
            from cryptography.fernet import Fernet

            Fernet(v.encode())
        except Exception as exc:
            raise ValueError(
                f"FERNET_KEY is invalid (must be a 32-byte URL-safe base64 key): {exc}"
            ) from exc
        return v

    @model_validator(mode="after")
    def validate_production_database_tls(self) -> "Settings":
        if self.environment.lower() != "production":
            return self
        if _database_url_has_ssl(self.database_url):
            return self
        raise ValueError("DATABASE_URL must enable TLS in production")

    def has_llm_api_key_configured(self) -> bool:
        return any(
            (key or "").strip()
            for key in (self.anthropic_api_key, self.openai_api_key, self.gemini_api_key)
        )

    def has_r2_snapshot_archive_configured(self) -> bool:
        return all(
            (value or "").strip()
            for value in (
                self.r2_endpoint_url,
                self.r2_bucket,
                self.r2_access_key_id,
                self.r2_secret_access_key,
            )
        )


def _database_url_has_ssl(database_url: str) -> bool:
    parsed = urlparse(database_url)
    if is_railway_managed_postgres_host(parsed.hostname):
        return True
    query = parse_qs(parsed.query)
    ssl_values = [value.lower() for value in query.get("ssl", [])]
    sslmode_values = [value.lower() for value in query.get("sslmode", [])]

    has_ssl_toggle = any(value in {"1", "true", "require"} for value in ssl_values)
    has_sslmode = any(value in {"require", "verify-ca", "verify-full"} for value in sslmode_values)
    return has_ssl_toggle or has_sslmode


settings = Settings()  # type: ignore[call-arg]
