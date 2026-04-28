import logging
from typing import Any
from urllib.parse import urlparse

from app.config import settings
from app.observability import init_observability
from app.queue.connection import format_redis_target
from app.queue.recovery import recover_stale_running_reviews
from arq.connections import RedisSettings
from arq.constants import default_queue_name
from arq.cron import cron

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

_logger.warning(
    "ARQ worker Redis target %s queue=%s (must match API log line; shell REDIS_URL overrides .env.local)",
    format_redis_target(settings.redis_url),
    default_queue_name,
)

from app.agent.runner import run_review  # noqa: E402
from app.agent.snapshot import archive_expired_snapshots  # noqa: E402
from app.agent.external.orchestrator import (  # noqa: E402
    run_external_eval_prepass,
    run_external_eval_shard,
    run_external_eval_synthesize,
)
from app.llm.maintenance import refresh_llm_catalog  # noqa: E402
from app.telemetry.finding_outcomes import (  # noqa: E402
    classify_pending_outcomes_nightly,
    classify_pr_outcomes_for_closed_pr,
)


async def review_pr(
    ctx: dict[str, Any],
    review_id: int,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    user_github_id: int | None = None,
) -> None:
    await run_review(
        review_id,
        installation_id,
        owner,
        repo,
        pr_number,
        head_sha,
        user_github_id=user_github_id,
        redis=ctx.get("redis"),
    )


async def classify_pr_outcomes(
    ctx: dict[str, Any],
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
) -> None:
    await classify_pr_outcomes_for_closed_pr(installation_id, owner, repo, pr_number)


async def classify_pending_outcomes(ctx: dict[str, Any]) -> None:
    await classify_pending_outcomes_nightly()


async def archive_review_snapshots(ctx: dict[str, Any]) -> None:
    archived = await archive_expired_snapshots()
    ctx["archived_review_snapshots"] = archived


async def external_eval_prepass(ctx: dict[str, Any], external_eval_id: int) -> None:
    await run_external_eval_prepass(eval_id=external_eval_id, redis=ctx.get("redis"))


async def external_eval_shard(ctx: dict[str, Any], shard_id: int) -> None:
    await run_external_eval_shard(shard_id=shard_id, redis=ctx.get("redis"))


async def external_eval_synthesize(ctx: dict[str, Any], external_eval_id: int) -> None:
    await run_external_eval_synthesize(eval_id=external_eval_id)


async def worker_startup(ctx: dict[str, Any]) -> None:
    init_observability("worker")
    recovered = await recover_stale_running_reviews()
    ctx["recovered_stale_reviews"] = recovered


class WorkerSettings:
    functions = [
        review_pr,
        classify_pr_outcomes,
        classify_pending_outcomes,
        archive_review_snapshots,
        refresh_llm_catalog,
        external_eval_prepass,
        external_eval_shard,
        external_eval_synthesize,
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = default_queue_name
    max_tries = 1
    max_jobs = 5
    job_timeout = 300
    keep_result = 3600
    on_startup = worker_startup
    cron_jobs = [
        cron(classify_pending_outcomes, hour=3, minute=0),
        cron(archive_review_snapshots, hour=4, minute=15),
        cron(refresh_llm_catalog, hour=2, minute=30),
    ]
