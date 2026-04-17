import logging
from app.github.client import GitHubClient

logger = logging.getLogger(__name__)


async def handle_pull_request(payload: dict) -> None:
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

    # TODO Phase 2: enqueue to ARQ/Redis worker
    # await queue_review_job(installation_id, owner, repo_name, pr_number, head_sha)
