import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from app.config import settings
from app.db.models import Review
from app.db.session import AsyncSessionLocal, set_installation_context

router = APIRouter()
logger = logging.getLogger(__name__)


def _split_repo_full_name(repo_full_name: str) -> tuple[str, str]:
    owner_repo = repo_full_name.split("/", 1)
    if len(owner_repo) != 2 or not owner_repo[0] or not owner_repo[1]:
        raise ValueError(f"Invalid repo_full_name: {repo_full_name}")
    return owner_repo[0], owner_repo[1]


def _require_admin_key(x_admin_api_key: str | None) -> None:
    if not settings.admin_retry_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin retry endpoint is not configured",
        )
    if not x_admin_api_key or not hmac.compare_digest(x_admin_api_key, settings.admin_retry_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


@router.post("/reviews/{review_id}/retry")
async def retry_review(
    request: Request,
    review_id: int,
    x_admin_api_key: str | None = Header(default=None),
    installation_id: int | None = Query(default=None, ge=1),
    force: bool = Query(default=False),
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

        job = await request.app.state.redis.enqueue_job(
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
