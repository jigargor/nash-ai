import hmac
import logging
import time

from app.config import settings
from app.db.models import Review
from app.queue.connection import require_app_redis
from app.db.session import AsyncSessionLocal, set_installation_context
from app.github.utils import split_repo_full_name as _split_repo_full_name
from fastapi import APIRouter, Header, HTTPException, Query, Request, status

router = APIRouter()
logger = logging.getLogger(__name__)

_ADMIN_RATE_LIMIT = 5
_ADMIN_RATE_WINDOW = 60


def _require_admin_key(x_admin_api_key: str | None) -> None:
    if not settings.admin_retry_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin retry endpoint is not configured",
        )
    if not x_admin_api_key or not hmac.compare_digest(x_admin_api_key, settings.admin_retry_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


async def _check_admin_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"admin:retry:{client_ip}"
    redis = require_app_redis(request)
    now = time.time()
    cutoff = now - _ADMIN_RATE_WINDOW
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, _ADMIN_RATE_WINDOW)
    _, count, _, _ = await pipe.execute()
    if int(count) >= _ADMIN_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Admin rate limit exceeded: max {_ADMIN_RATE_LIMIT} requests per {_ADMIN_RATE_WINDOW}s",
        )


@router.post("/reviews/{review_id}/retry")
async def retry_review(
    request: Request,
    review_id: int,
    x_admin_api_key: str | None = Header(default=None),
    installation_id: int | None = Query(default=None, ge=1),
    force: bool = Query(default=False),
) -> dict[str, object]:
    _require_admin_key(x_admin_api_key)
    await _check_admin_rate_limit(request)

    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

        if installation_id is None:
            await set_installation_context(session, int(review.installation_id))
        elif int(review.installation_id) != installation_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch")

        if review.status != "failed" and not force:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Review status is '{review.status}'. Use force=true to retry anyway.",
            )

        try:
            owner, repo = _split_repo_full_name(review.repo_full_name)
        except ValueError as exc:
            logger.exception("Invalid review repo name review_id=%s", review_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

        if not settings.has_llm_api_key_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No LLM API key configured (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)",
            )

        redis = require_app_redis(request)
        job = await redis.enqueue_job(
            "review_pr",
            int(review.id),
            int(review.installation_id),
            owner,
            repo,
            int(review.pr_number),
            review.pr_head_sha,
        )
        if job is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to enqueue retry job")

        review.status = "queued"
        review.started_at = None
        review.completed_at = None
        await session.commit()

    logger.warning("Requeued review_id=%s as job_id=%s", review_id, job.job_id)
    return {"ok": True, "review_id": review_id, "job_id": job.job_id}


@router.get("/reviews/{review_id}/debug")
async def get_review_debug(
    review_id: int,
    x_admin_api_key: str | None = Header(default=None),
    installation_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    _require_admin_key(x_admin_api_key)

    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

        if installation_id is None:
            await set_installation_context(session, int(review.installation_id))
        elif int(review.installation_id) != installation_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch")

        findings_payload = review.findings if isinstance(review.findings, dict) else {}
        findings_list = findings_payload.get("findings")
        kept_findings_count = len(findings_list) if isinstance(findings_list, list) else 0
        summary = findings_payload.get("summary")
        summary_text = summary if isinstance(summary, str) else None

        return {
            "review_id": int(review.id),
            "installation_id": int(review.installation_id),
            "repo_full_name": review.repo_full_name,
            "pr_number": int(review.pr_number),
            "status": review.status,
            "kept_findings_count": kept_findings_count,
            "summary": summary_text,
            "debug_artifacts": review.debug_artifacts,
            "completed_at": review.completed_at.isoformat() if review.completed_at else None,
        }
