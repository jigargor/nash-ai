from pathlib import Path

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
    redis_url: str = "redis://localhost:6379"
    fernet_key: str
    anthropic_api_key: str
    environment: str = "development"


settings = Settings()  # type: ignore[call-arg]
