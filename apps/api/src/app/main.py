from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.queue.connection import create_redis_pool
from app.webhooks.router import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Database schema is managed by Alembic migrations.
    app.state.redis = await create_redis_pool()
    yield
    await app.state.redis.close()


app = FastAPI(title="AI Code Review API", lifespan=lifespan)
app.include_router(webhook_router, prefix="/webhooks")


@app.get("/health")
async def health():
    return {"status": "ok"}
