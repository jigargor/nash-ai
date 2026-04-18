import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# The app settings object is strict, so provide benign defaults when the
# migration environment imports app modules without a fully populated .env.
# DATABASE_URL must be set before importing app.* (session.py loads Settings).
# Default matches local docker-compose Postgres (host port 5433).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://dev:dev@localhost:5433/codereview",
)
os.environ.setdefault("GITHUB_APP_ID", "0")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "placeholder")
os.environ.setdefault("GITHUB_CLIENT_ID", "placeholder")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "placeholder")
os.environ.setdefault("FERNET_KEY", "placeholder")
os.environ.setdefault("ANTHROPIC_API_KEY", "placeholder")

database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.db.session import Base  # noqa: E402
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
