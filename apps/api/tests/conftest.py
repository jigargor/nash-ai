from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.api import router as api_router
from app.config import settings
from app.db.models import Installation, Review
from app.db.session import AsyncSessionLocal, engine, set_installation_context


# ---------------------------------------------------------------------------
# Shared test helpers — importable by any test file
# (these are plain functions, not fixtures; test files import them explicitly)
# ---------------------------------------------------------------------------


@dataclass
class _FakeJob:
    job_id: str


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def enqueue_job(self, *args: object, **_kwargs: object) -> _FakeJob:
        self.calls.append(args)
        return _FakeJob(job_id=f"job-{len(self.calls)}")


def _random_installation_id() -> int:
    return int(str(uuid4().int)[:9])


def _auth_headers() -> dict[str, str]:
    if settings.api_access_key:
        return {"X-Api-Key": settings.api_access_key}
    return {}


async def _insert_installation(installation_id: int, *, suspended: bool = False) -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"acme-{installation_id}",
                account_type="Organization",
                suspended_at=datetime.now(timezone.utc) if suspended else None,
            )
        )
        await session.commit()


async def _insert_review(
    installation_id: int,
    *,
    repo_full_name: str = "acme/repo",
    status: str = "done",
    findings: dict[str, object] | None = None,
) -> int:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = Review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=7,
            pr_head_sha="a" * 40,
            status=status,
            model_provider="anthropic",
            model="claude-sonnet-4-5",
            findings=findings,
            debug_artifacts={},
            tokens_used=123,
            cost_usd=0.25,
        )
        session.add(review)
        await session.flush()
        review_id = int(review.id)
        await session.commit()
    return review_id


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_test_app() -> FastAPI:
    """FastAPI app with the main API router and fake Redis state."""
    application = FastAPI()
    application.include_router(api_router.router)
    application.state.redis = _FakeRedis()
    return application


@pytest.fixture
async def api_client(api_test_app: FastAPI) -> httpx.AsyncIterator[httpx.AsyncClient]:
    """httpx client wired to api_test_app."""
    transport = httpx.ASGITransport(app=api_test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


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
