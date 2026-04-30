from app.config import settings
from app.errors.exceptions import DependencyUnavailableError
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
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
        raise DependencyUnavailableError(
            dependency="redis",
            message="Redis unavailable",
            code="DEPENDENCY_REDIS_UNAVAILABLE",
        )
    return redis
