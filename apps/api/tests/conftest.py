import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


def _default_test_database_url() -> str:
    database_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://dev:dev@localhost:5433/codereview"
    )
    parsed = urlparse(database_url)
    if parsed.path in {"", "/"}:
        return urlunparse(parsed._replace(path="/codereview_test"))
    current_name = parsed.path.lstrip("/")
    return urlunparse(parsed._replace(path=f"/{current_name}_test"))


def _to_asyncpg_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _replace_database(url: str, database_name: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{database_name}"))


async def _ensure_database_exists(test_database_url: str) -> None:
    database_name = urlparse(test_database_url).path.lstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise ValueError("Unsafe TEST_DATABASE_URL database name")

    admin_url = _to_asyncpg_url(_replace_database(test_database_url, "postgres"))
    connection = await asyncpg.connect(admin_url)
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", database_name
        )
        if exists:
            return
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.getenv("TEST_DATABASE_URL", _default_test_database_url())


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database(test_database_url: str) -> None:
    asyncio.run(_ensure_database_exists(test_database_url))

    os.environ["DATABASE_URL"] = test_database_url
    os.environ.setdefault("GITHUB_APP_ID", "0")
    os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
    os.environ.setdefault("GITHUB_CLIENT_ID", "test-client-id")
    os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-client-secret")
    os.environ.setdefault("FERNET_KEY", "4nYA5RU2f22W4DvwW8Hpt4W6YKfYwQMUqlGQv6ygfA4=")
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")

    apps_api_dir = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(apps_api_dir / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(apps_api_dir / "alembic"))
    command.upgrade(alembic_config, "head")


@pytest.fixture(scope="session")
async def test_engine(test_database_url: str) -> AsyncEngine:
    engine = create_async_engine(test_database_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncSession:
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
