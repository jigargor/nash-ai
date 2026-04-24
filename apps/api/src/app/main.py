import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.api.router import router as api_router
from app.admin.router import router as admin_router
from app.config import settings
from app.observability import init_observability
from app.db.session import engine
from app.queue.connection import create_redis_pool, format_redis_target
from app.webhooks.router import router as webhook_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_observability("api")
    # Database schema is managed by Alembic migrations.
    db = urlparse(settings.database_url)
    logger.warning(
        "DB connection target %s:%s (user=%s). If this is wrong, check: shell DATABASE_URL overrides .env.local.",
        db.hostname or "",
        db.port or "default",
        db.username or "",
    )
    if db.port == 5432 and (db.hostname in {"localhost", "127.0.0.1", "::1"} or not db.hostname):
        logger.warning(
            "Using port 5432 on localhost — often not Compose (this repo uses host port 5433). "
            "Unset DATABASE_URL in the shell or point it at ...5433... to avoid role dev does not exist."
        )
    logger.warning(
        "Redis pool target %s (worker must use the same REDIS_URL; shell env overrides .env.local).",
        format_redis_target(settings.redis_url),
    )
    app.state.redis = await create_redis_pool()
    yield
    await app.state.redis.close()
    await engine.dispose()


app = FastAPI(title="AI Code Review API", lifespan=lifespan)
if settings.web_app_url:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_app_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
app.include_router(webhook_router, prefix="/webhooks")
app.include_router(admin_router, prefix="/admin")
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/queue")
async def health_queue(request: Request) -> dict[str, Any]:
    """Debug: ARQ queue depth. If this grows but the worker stays idle, Redis URL or worker process is wrong."""
    redis = request.app.state.redis
    queued_jobs = await redis.zcard(redis.default_queue_name)
    return {
        "queue_name": redis.default_queue_name,
        "queued_jobs": queued_jobs,
        "redis_target": format_redis_target(settings.redis_url),
    }
