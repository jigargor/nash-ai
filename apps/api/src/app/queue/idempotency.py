from arq.connections import ArqRedis

REVIEW_SUBMISSION_LOCK_TTL_SECONDS = 15 * 60


def review_submission_lock_key(
    installation_id: int,
    pr_number: int,
    head_sha: str,
) -> str:
    return f"review-submit:{installation_id}:{pr_number}:{head_sha}"


async def acquire_review_submission_lock(
    redis: ArqRedis,
    *,
    installation_id: int,
    pr_number: int,
    head_sha: str,
    ttl_seconds: int = REVIEW_SUBMISSION_LOCK_TTL_SECONDS,
) -> bool:
    lock_key = review_submission_lock_key(installation_id, pr_number, head_sha)
    acquired = await redis.set(lock_key, "1", ex=ttl_seconds, nx=True)
    return bool(acquired)
