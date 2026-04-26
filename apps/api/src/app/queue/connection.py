from app.config import settings
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import HTTPException, status
from starlette.requests import Request


def format_redis_target(redis_url: str) -> str:
    """Human-readable host:port db=N for logs (no password)."""
    rs = RedisSettings.from_dsn(redis_url)
    host = rs.host if isinstance(rs.host, str) else repr(rs.host)
    return f"{host}:{rs.port} db={rs.database}"


async def create_redis_pool() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


def require_app_redis(request: Request) -> ArqRedis:
    """Raise 503 if the app started without Redis (e.g. connection failed at boot)."""
    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis unavailable",
        )
    return redis
