from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    github_private_key_path: Path = Path("private-key.pem")
    github_client_id: str
    github_client_secret: str
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    db_command_timeout_seconds: int = 30
    db_statement_timeout_ms: int | None = None
    db_require_ssl_in_production: bool = True
    redis_url: str = "redis://localhost:6379"
    fernet_key: str
    anthropic_api_key: str
    environment: str = "development"
    log_webhook_payloads: bool = False
    admin_retry_api_key: str | None = None

    @field_validator("github_app_id", mode="before")
    @classmethod
    def strip_github_app_id(cls, v: object) -> str:
        if v is None:
            raise ValueError("GITHUB_APP_ID is required")
        return str(v).strip()

    @field_validator("github_private_key_path", mode="after")
    @classmethod
    def resolve_github_private_key_path(cls, v: Path) -> Path:
        """Paths from .env are relative to apps/api (not the process cwd).

        Workers are often started from apps/api/src; without this, ./private-key.pem
        resolves to apps/api/src/private-key.pem and GitHub JWT auth returns 401.
        """
        if v.is_absolute():
            return v.resolve()
        apps_api = Path(__file__).resolve().parent.parent.parent
        return (apps_api / v).resolve()

    @model_validator(mode="after")
    def validate_production_database_tls(self) -> "Settings":
        if self.environment.lower() != "production" or not self.db_require_ssl_in_production:
            return self
        if _database_url_has_ssl(self.database_url):
            return self
        raise ValueError("DATABASE_URL must enable TLS in production")


def _database_url_has_ssl(database_url: str) -> bool:
    query = parse_qs(urlparse(database_url).query)
    ssl_values = [value.lower() for value in query.get("ssl", [])]
    sslmode_values = [value.lower() for value in query.get("sslmode", [])]

    has_ssl_toggle = any(value in {"1", "true", "require"} for value in ssl_values)
    has_sslmode = any(value in {"require", "verify-ca", "verify-full"} for value in sslmode_values)
    return has_ssl_toggle or has_sslmode


settings = Settings()  # type: ignore[call-arg]
