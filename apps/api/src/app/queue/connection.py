from app.config import settings
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


def format_redis_target(redis_url: str) -> str:
    """Human-readable host:port db=N for logs (no password)."""
    rs = RedisSettings.from_dsn(redis_url)
    host = rs.host if isinstance(rs.host, str) else repr(rs.host)
    return f"{host}:{rs.port} db={rs.database}"


async def create_redis_pool() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))
