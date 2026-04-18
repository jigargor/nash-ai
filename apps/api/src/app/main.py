import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI

from app.config import settings
from app.db.session import engine
from app.queue.connection import create_redis_pool
from app.webhooks.router import router as webhook_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    app.state.redis = await create_redis_pool()
    yield
    await app.state.redis.close()
    await engine.dispose()


app = FastAPI(title="AI Code Review API", lifespan=lifespan)
app.include_router(webhook_router, prefix="/webhooks")


@app.get("/health")
async def health():
    return {"status": "ok"}
