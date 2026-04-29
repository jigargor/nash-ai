from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base
from app.db.url import normalize_asyncpg_database_url

connect_args: dict[str, object] = {
    "timeout": settings.db_connect_timeout_seconds,
    "command_timeout": settings.db_command_timeout_seconds,
    "server_settings": {"statement_timeout": str(settings.db_statement_timeout_ms)},
}

engine = create_async_engine(
    normalize_asyncpg_database_url(settings.database_url),
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_pre_ping=True,
    connect_args=connect_args,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def set_installation_context(session: AsyncSession, installation_id: int) -> None:
    await session.execute(
        text("SELECT set_config('app.current_installation_id', :installation_id, true)"),
        {"installation_id": str(installation_id)},
    )


async def set_user_context(session: AsyncSession, github_id: int) -> None:
    """Set the per-request user context for RLS policies on user-scoped tables."""
    await session.execute(
        text("SELECT set_config('app.current_user_github_id', :github_id, true)"),
        {"github_id": str(github_id)},
    )
