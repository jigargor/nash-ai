import asyncio
import os
import warnings
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from app.db.url import is_railway_managed_postgres_host, normalize_asyncpg_database_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config


def _candidate_env_files() -> tuple[Path, ...]:
    here = Path(__file__).resolve().parent  # .../apps/api/alembic
    apps_api = here.parent  # .../apps/api
    repo_root = apps_api.parent.parent  # repo root (parent of apps/)
    return (
        apps_api / ".env",
        apps_api / ".env.local",
        repo_root / ".env",
        repo_root / ".env.local",
    )


def _read_env_value_from_files(key: str) -> str | None:
    for env_file in _candidate_env_files():
        if not env_file.is_file():
            continue
        try:
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                left, right = line.split("=", 1)
                if left.strip() != key:
                    continue
                value = right.strip().strip('"').strip("'")
                if value:
                    return value
        except OSError:
            continue
    return None


def _database_url_has_tls(database_url: str) -> bool:
    parsed = urlparse(database_url)
    if is_railway_managed_postgres_host(parsed.hostname):
        return True
    query = parse_qs(parsed.query)
    ssl_values = [value.lower() for value in query.get("ssl", [])]
    sslmode_values = [value.lower() for value in query.get("sslmode", [])]
    has_ssl_toggle = any(value in {"1", "true", "require"} for value in ssl_values)
    has_sslmode = any(value in {"require", "verify-ca", "verify-full"} for value in sslmode_values)
    return has_ssl_toggle or has_sslmode


# The app settings object is strict; allow local convenience defaults only in
# non-production environments. Worker/API production containers must provide an
# explicit DATABASE_URL so Alembic never points at localhost by mistake.
environment = (
    (os.environ.get("ENVIRONMENT") or "").strip()
    or (_read_env_value_from_files("ENVIRONMENT") or "").strip()
    or "development"
).lower()
configured_database_url = (
    (os.environ.get("DATABASE_URL") or "").strip()
    or (_read_env_value_from_files("DATABASE_URL") or "").strip()
)
if configured_database_url:
    if environment == "production" and not _database_url_has_tls(configured_database_url):
        raise RuntimeError(
            "DATABASE_URL must enable TLS in production for Alembic "
            "(use ?ssl=require or sslmode=require)."
        )
    os.environ["DATABASE_URL"] = configured_database_url
elif environment == "production":
    raise RuntimeError(
        "DATABASE_URL is required for Alembic in production. "
        "Set DATABASE_URL explicitly (environment variable or .env file) for worker/API containers."
    )
else:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://dev:dev@localhost:5433/codereview"
    warnings.warn(
        "DATABASE_URL not set — using local dev default (localhost:5433/codereview). "
        "Set DATABASE_URL explicitly in CI/CD to avoid accidental migrations against the wrong database.",
        stacklevel=1,
    )
os.environ.setdefault("GITHUB_APP_ID", "0")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "placeholder")
os.environ.setdefault("GITHUB_CLIENT_ID", "placeholder")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "placeholder")
os.environ.setdefault("ANTHROPIC_API_KEY", "placeholder")
# Fernet key must be a valid 32-byte URL-safe base64 key for the startup validator.
# Generate a random throwaway key if none is set — it is never used during migrations.
if not os.environ.get("FERNET_KEY"):
    from cryptography.fernet import Fernet

    os.environ["FERNET_KEY"] = Fernet.generate_key().decode()

database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", normalize_asyncpg_database_url(database_url))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.db.base import Base  # noqa: E402
import app.db.models  # noqa: F401,E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
