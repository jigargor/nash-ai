import asyncio
import hmac
import json
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from app.config import settings
from app.db.models import Installation, Review, ReviewModelAudit
from app.db.session import AsyncSessionLocal, set_installation_context
from app.github.utils import split_repo_full_name as _split_repo_full_name
from app.telemetry.finding_outcomes import list_review_finding_outcomes, summarize_finding_outcomes
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key auth is not configured")
    if not settings.api_access_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key")


router = APIRouter(prefix="/api/v1", dependencies=[Depends(_verify_api_access)])


class RepoAccumulator(TypedDict):
    installation_id: int
    repo_full_name: str
    review_count: int
    failed_review_count: int
    total_tokens: int
    estimated_cost_usd: Decimal
    latest_review_id: int
    latest_pr_number: int
    latest_status: str
    last_review_at: datetime


async def _list_installation_rows(
    session: AsyncSession,
    *,
    active_only: bool = True,
    limit: int = 100,
) -> list[Installation]:
    stmt = select(Installation).order_by(Installation.installed_at.desc()).limit(limit)
    if active_only:
        stmt = stmt.where(Installation.suspended_at.is_(None))
    rows = await session.scalars(stmt)
    return list(rows)


def _review_list_item(review: Review) -> dict[str, object]:
    return {
        "id": int(review.id),
        "installation_id": int(review.installation_id),
        "repo_full_name": review.repo_full_name,
        "pr_number": int(review.pr_number),
        "status": review.status,
        "model_provider": review.model_provider,
        "model": review.model,
        "tokens_used": int(review.tokens_used) if review.tokens_used is not None else None,
        "cost_usd": str(review.cost_usd) if review.cost_usd is not None else None,
        "created_at": review.created_at.isoformat(),
        "completed_at": review.completed_at.isoformat() if review.completed_at is not None else None,
    }


@router.get("/installations")
async def list_installations(
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        installations = await _list_installation_rows(session, active_only=active_only, limit=limit)
        return [
            {
                "installation_id": int(item.installation_id),
                "account_login": item.account_login,
                "account_type": item.account_type,
                "active": item.suspended_at is None,
                "suspended_at": item.suspended_at.isoformat() if item.suspended_at is not None else None,
            }
            for item in installations
        ]


@router.get("/repos")
async def list_repos(
    installation_id: int | None = Query(default=None, ge=1),
    active_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            installation_ids = [installation_id]
        else:
            installations = await _list_installation_rows(session, active_only=active_only, limit=100)
            installation_ids = [int(item.installation_id) for item in installations]

        repos: dict[tuple[int, str], RepoAccumulator] = {}
        for current_installation_id in installation_ids:
            await set_installation_context(session, current_installation_id)
            rows = await session.scalars(
                select(Review)
                .where(Review.installation_id == current_installation_id)
                .order_by(Review.created_at.desc())
                .limit(limit)
            )
            for review in rows:
                key = (int(review.installation_id), review.repo_full_name)
                repo = repos.setdefault(
                    key,
                    {
                        "installation_id": int(review.installation_id),
                        "repo_full_name": review.repo_full_name,
                        "review_count": 0,
                        "failed_review_count": 0,
                        "total_tokens": 0,
                        "estimated_cost_usd": Decimal("0"),
                        "latest_review_id": int(review.id),
                        "latest_pr_number": int(review.pr_number),
                        "latest_status": review.status,
                        "last_review_at": review.created_at,
                    },
                )
                repo["review_count"] += 1
                if review.status == "failed":
                    repo["failed_review_count"] += 1
                repo["total_tokens"] += int(review.tokens_used or 0)
                repo["estimated_cost_usd"] += Decimal(str(review.cost_usd or 0))

                if review.created_at >= repo["last_review_at"]:
                    repo["latest_review_id"] = int(review.id)
                    repo["latest_pr_number"] = int(review.pr_number)
                    repo["latest_status"] = review.status
                    repo["last_review_at"] = review.created_at

        sorted_repos = sorted(
            repos.values(),
            key=lambda item: item["last_review_at"],
            reverse=True,
        )
        return [
            {
                **repo,
                "estimated_cost_usd": str(repo["estimated_cost_usd"]),
                "last_review_at": repo["last_review_at"].isoformat(),
            }
            for repo in sorted_repos[:limit]
        ]


@router.get("/reviews")
async def list_reviews(
    installation_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
            reviews = await session.scalars(
                select(Review)
                .where(Review.installation_id == installation_id)
                .order_by(Review.created_at.desc())
                .limit(limit)
            )
            return [_review_list_item(review) for review in reviews]

        installations = await _list_installation_rows(session, active_only=True, limit=100)
        all_reviews: list[Review] = []
        for installation in installations:
            await set_installation_context(session, int(installation.installation_id))
            reviews = await session.scalars(
                select(Review)
                .where(Review.installation_id == int(installation.installation_id))
                .order_by(Review.created_at.desc())
                .limit(limit)
            )
            all_reviews.extend(reviews)

        all_reviews.sort(key=lambda review: review.created_at, reverse=True)
        return [_review_list_item(review) for review in all_reviews[:limit]]


@router.get("/reviews/{review_id}")
async def get_review(review_id: int, installation_id: int | None = Query(default=None, ge=1)) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch")

        return {
            "id": int(review.id),
            "installation_id": int(review.installation_id),
            "repo_full_name": review.repo_full_name,
            "pr_number": int(review.pr_number),
            "pr_head_sha": review.pr_head_sha,
            "status": review.status,
            "model_provider": review.model_provider,
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
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch")

        return {
            "review_id": int(review.id),
            "finding_outcomes": await list_review_finding_outcomes(int(review.id), int(review.installation_id)),
        }


@router.get("/reviews/{review_id}/model-audits")
async def get_review_model_audits(
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
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch")
        rows = await session.scalars(
            select(ReviewModelAudit)
            .where(ReviewModelAudit.review_id == review_id)
            .order_by(ReviewModelAudit.created_at.asc())
        )
        audits = [
            {
                "id": int(row.id),
                "run_id": row.run_id,
                "stage": row.stage,
                "provider": row.provider,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "input_tokens": int(row.input_tokens),
                "output_tokens": int(row.output_tokens),
                "total_tokens": int(row.total_tokens),
                "findings_count": int(row.findings_count) if row.findings_count is not None else None,
                "accepted_findings_count": (
                    int(row.accepted_findings_count) if row.accepted_findings_count is not None else None
                ),
                "conflict_score": int(row.conflict_score) if row.conflict_score is not None else None,
                "decision": row.decision,
                "metadata_json": row.metadata_json,
                "created_at": row.created_at.isoformat() if row.created_at is not None else None,
            }
            for row in rows
        ]
    return {"review_id": review_id, "model_audits": audits}


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
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch")

        if not settings.has_llm_api_key_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No LLM API key configured (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)",
            )

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
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch")

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
                elif int(review.installation_id) != installation_id:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'installation_id mismatch'})}\n\n"
                    return

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
