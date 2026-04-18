import logging
from arq.connections import ArqRedis
from sqlalchemy import select

from app.db.models import Installation, Review
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def queue_pull_request_review(redis: ArqRedis, payload: dict) -> None:
    installation_id = payload["installation"]["id"]
    repo = payload["repository"]
    pr = payload["pull_request"]

    owner, repo_name = repo["full_name"].split("/")
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]

    logger.warning(
        "PR webhook parsed installation_id=%s repo=%s pr_number=%s head_sha=%s",
        installation_id,
        repo["full_name"],
        pr_number,
        head_sha,
    )
    async with AsyncSessionLocal() as session:
        installation = await session.scalar(
            select(Installation).where(Installation.installation_id == installation_id)
        )
        if installation is None:
            owner = repo.get("owner") or {}
            session.add(
                Installation(
                    installation_id=installation_id,
                    account_login=owner.get("login", "unknown"),
                    account_type=owner.get("type", "unknown"),
                )
            )
            await session.flush()

        review = Review(
            installation_id=installation_id,
            repo_full_name=repo["full_name"],
            pr_number=pr_number,
            pr_head_sha=head_sha,
            model="claude-sonnet-4-5",
            status="queued",
        )
        session.add(review)
        await session.flush()
        review_id = review.id
        await session.commit()

    job = await redis.enqueue_job(
        "review_pr",
        review_id,
        installation_id,
        owner,
        repo_name,
        pr_number,
        head_sha,
    )
    logger.warning(
        "Queued review job review_id=%s job_id=%s repo=%s pr_number=%s",
        review_id,
        job.job_id if job else "unknown",
        repo["full_name"],
        pr_number,
    )
