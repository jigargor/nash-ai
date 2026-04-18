from arq.connections import RedisSettings

from app.agent.runner import run_review
from app.config import settings


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
