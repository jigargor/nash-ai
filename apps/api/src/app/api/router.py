import asyncio
import hmac
import json
from collections.abc import AsyncIterator

from app.config import settings
from app.db.models import Installation, Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.github.utils import split_repo_full_name as _split_repo_full_name
from app.telemetry.finding_outcomes import list_review_finding_outcomes, summarize_finding_outcomes
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_access_key:
        return  # key not configured — open access (backwards-compatible default)
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key")


router = APIRouter(prefix="/api/v1", dependencies=[Depends(_verify_api_access)])


@router.get("/installations")
async def list_installations(limit: int = Query(default=50, ge=1, le=100)) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        installations = await session.scalars(select(Installation).order_by(Installation.installed_at.desc()).limit(limit))
        return [
            {
                "installation_id": int(item.installation_id),
                "account_login": item.account_login,
                "account_type": item.account_type,
            }
            for item in installations
        ]


@router.get("/reviews")
async def list_reviews(
    installation_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        reviews = await session.scalars(select(Review).order_by(Review.created_at.desc()).limit(limit))
        return [
            {
                "id": int(review.id),
                "repo_full_name": review.repo_full_name,
                "pr_number": int(review.pr_number),
                "status": review.status,
                "tokens_used": int(review.tokens_used) if review.tokens_used is not None else None,
                "cost_usd": str(review.cost_usd) if review.cost_usd is not None else None,
            }
            for review in reviews
        ]


@router.get("/reviews/{review_id}")
async def get_review(review_id: int, installation_id: int | None = Query(default=None, ge=1)) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            await set_installation_context(session, int(review.installation_id))

        return {
            "id": int(review.id),
            "installation_id": int(review.installation_id),
            "repo_full_name": review.repo_full_name,
            "pr_number": int(review.pr_number),
            "pr_head_sha": review.pr_head_sha,
            "status": review.status,
            "model": review.model,
            "findings": review.findings,
            "tokens_used": int(review.tokens_used) if review.tokens_used is not None else None,
            "cost_usd": str(review.cost_usd) if review.cost_usd is not None else None,
            "created_at": review.created_at.isoformat(),
            "completed_at": review.completed_at.isoformat() if review.completed_at is not None else None,
            "finding_outcomes": await list_review_finding_outcomes(int(review.id), int(review.installation_id)),
        }


@router.get("/reviews/{review_id}/outcomes")
async def get_review_outcomes(
    review_id: int,
    installation_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
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

        return {
            "review_id": int(review.id),
            "finding_outcomes": await list_review_finding_outcomes(int(review.id), int(review.installation_id)),
        }


@router.get("/telemetry/outcomes/summary")
async def get_outcome_summary(
    installation_id: int | None = Query(default=None, ge=1),
    repo_full_name: str | None = Query(default=None),
) -> dict[str, object]:
    summary = await summarize_finding_outcomes(
        installation_id=installation_id,
        repo_full_name=repo_full_name,
    )
    return {
        "installation_id": installation_id,
        "repo_full_name": repo_full_name,
        **summary,
    }


@router.post("/reviews/{review_id}/rerun")
async def rerun_review(
    request: Request,
    review_id: int,
    installation_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            await set_installation_context(session, int(review.installation_id))

        owner, repo = _split_repo_full_name(review.repo_full_name)
        job = await request.app.state.redis.enqueue_job(
            "review_pr",
            int(review.id),
            int(review.installation_id),
            owner,
            repo,
            int(review.pr_number),
            review.pr_head_sha,
        )
        review.status = "queued"
        review.started_at = None
        review.completed_at = None
        await session.commit()

    return {"ok": True, "review_id": review_id, "job_id": job.job_id if job else None}


@router.post("/reviews/{review_id}/findings/{finding_index}/dismiss")
async def dismiss_finding(
    review_id: int,
    finding_index: int,
    installation_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            await set_installation_context(session, int(review.installation_id))

        debug_artifacts = review.debug_artifacts or {}
        dismissed = list(debug_artifacts.get("dismissed_findings", []))
        if finding_index not in dismissed:
            dismissed.append(finding_index)
        debug_artifacts["dismissed_findings"] = dismissed
        review.debug_artifacts = debug_artifacts
        await session.commit()

    return {"ok": True, "review_id": review_id, "dismissed_finding_index": finding_index}


@router.get("/reviews/{review_id}/stream")
async def stream_review_events(
    review_id: int,
    installation_id: int | None = Query(default=None, ge=1),
) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        previous_status: str | None = None
        for _ in range(120):
            async with AsyncSessionLocal() as session:
                if installation_id is not None:
                    await set_installation_context(session, installation_id)
                review = await session.get(Review, review_id)
                if review is None:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Review not found'})}\n\n"
                    return
                if installation_id is None:
                    await set_installation_context(session, int(review.installation_id))

                if previous_status is None:
                    yield f"data: {json.dumps({'type': 'started', 'status': review.status})}\n\n"
                    previous_status = review.status
                elif review.status != previous_status:
                    yield f"data: {json.dumps({'type': 'status', 'status': review.status})}\n\n"
                    previous_status = review.status

                if review.status in {"done", "failed"}:
                    yield f"data: {json.dumps({'type': 'complete', 'status': review.status})}\n\n"
                    return

            await asyncio.sleep(2)

        yield f"data: {json.dumps({'type': 'error', 'message': 'Stream timeout'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
