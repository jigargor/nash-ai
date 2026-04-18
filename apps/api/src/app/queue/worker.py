import logging
from urllib.parse import urlparse

from arq.connections import RedisSettings

from app.config import settings

# Import order: log which DB URL this process will use *before* session.engine is created
# (runner → session binds engine at import). Worker is a separate process from uvicorn —
# shell DATABASE_URL overrides .env.local; fix the worker terminal if API works but jobs fail.
_logger = logging.getLogger(__name__)
_db = urlparse(settings.database_url)
_logger.warning(
    "ARQ worker DB target %s:%s user=%s (must match API; unset shell DATABASE_URL if wrong)",
    _db.hostname or "",
    _db.port or "default",
    _db.username or "",
)
if _db.port == 5432 and (_db.hostname in {"localhost", "127.0.0.1", "::1"} or not _db.hostname):
    _logger.warning(
        "Worker is using localhost:5432 — often not Docker Compose (this repo uses 5433). "
        "Run: Remove-Item Env:DATABASE_URL  OR  $env:DATABASE_URL='postgresql+asyncpg://dev:dev@localhost:5433/codereview'"
    )

from app.agent.runner import run_review  # noqa: E402


async def review_pr(
    ctx: dict,
    review_id: int,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
) -> None:
    await run_review(review_id, installation_id, owner, repo, pr_number, head_sha)


class WorkerSettings:
    functions = [review_pr]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 5
    job_timeout = 300
    keep_result = 3600
