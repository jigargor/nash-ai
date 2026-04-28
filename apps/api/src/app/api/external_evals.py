from __future__ import annotations

import hmac
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.external.github_public import PublicRepoError, list_repo_files, parse_public_repo_url, resolve_repo_ref
from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.config import settings
from app.db.models import (
    ExternalEvaluation,
    ExternalEvaluationFinding,
    ExternalEvaluationShard,
    InstallationUser,
    User,
)
from app.db.session import AsyncSessionLocal, set_installation_context
from app.queue.connection import require_app_redis


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(  # pragma: no cover
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key auth is not configured"
        )
    if not settings.api_access_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key"
        )


router = APIRouter(
    prefix="/api/v1/external-evals",
    dependencies=[Depends(_verify_api_access), Depends(get_current_dashboard_user)],
)


class ExternalEvalEstimateRequest(BaseModel):
    installation_id: int = Field(..., ge=1)
    repo_url: str = Field(..., min_length=1, max_length=500)
    target_ref: str | None = Field(default=None, max_length=255)


class ExternalEvalCreateRequest(ExternalEvalEstimateRequest):
    ack_confirmed: bool = Field(default=False)
    token_budget_cap: int = Field(default=2_000_000, ge=10_000, le=30_000_000)
    cost_budget_cap_usd: float = Field(default=25.0, ge=0.5, le=500.0)


class ExternalEvalCancelRequest(BaseModel):
    installation_id: int = Field(..., ge=1)


async def _allowed_installation_ids(current_user: CurrentDashboardUser) -> set[int]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(InstallationUser.installation_id)
                .join(User, User.id == InstallationUser.user_id)
                .where(User.github_id == current_user.github_id)
                .where(User.deleted_at.is_(None))
            )
        ).scalars()
        return {int(installation_id) for installation_id in rows}


def _require_installation_access(allowed_installation_ids: set[int], installation_id: int) -> None:
    if installation_id not in allowed_installation_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found")


async def _current_user_row_id(current_user: CurrentDashboardUser) -> int:
    async with AsyncSessionLocal() as session:
        user_id = await session.scalar(
            select(User.id)
            .where(User.github_id == current_user.github_id)
            .where(User.deleted_at.is_(None))
            .limit(1)
        )
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return int(user_id)


def _estimate_cost(file_count: int, total_bytes: int) -> tuple[int, Decimal]:
    estimated_tokens = max(int(total_bytes / 4), file_count * 180, 1200)
    estimated_cost = (Decimal(estimated_tokens) / Decimal(1_000_000)) * Decimal("0.20")
    return estimated_tokens, estimated_cost.quantize(Decimal("0.000001"))


@router.post("/estimate")
async def estimate_external_eval(
    payload: ExternalEvalEstimateRequest,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, payload.installation_id)
    try:
        owner, repo = parse_public_repo_url(payload.repo_url)
        repo_ref = await resolve_repo_ref(owner, repo, payload.target_ref)
        files = await list_repo_files(repo_ref)
    except PublicRepoError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    total_bytes = sum(item.size_bytes for item in files)
    estimated_tokens, estimated_cost = _estimate_cost(len(files), total_bytes)
    return {
        "owner": owner,
        "repo": repo,
        "target_ref": repo_ref.ref,
        "default_branch": repo_ref.default_branch,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "estimated_tokens": estimated_tokens,
        "estimated_cost_usd": str(estimated_cost),
        "ack_required": True,
        "warning": "Full-repository evaluation can be costly, especially for large repositories.",
    }


@router.post("")
async def create_external_eval(
    request: Request,
    payload: ExternalEvalCreateRequest,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    if not payload.ack_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Explicit acknowledgment is required before starting external evaluation.",
        )
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, payload.installation_id)
    user_id = await _current_user_row_id(current_user)
    try:
        owner, repo = parse_public_repo_url(payload.repo_url)
        repo_ref = await resolve_repo_ref(owner, repo, payload.target_ref)
        files = await list_repo_files(repo_ref)
    except PublicRepoError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    total_bytes = sum(item.size_bytes for item in files)
    estimated_tokens, estimated_cost = _estimate_cost(len(files), total_bytes)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, payload.installation_id)
        evaluation = ExternalEvaluation(
            installation_id=payload.installation_id,
            requested_by_user_id=user_id,
            repo_url=payload.repo_url,
            owner=owner,
            repo=repo,
            target_ref=repo_ref.ref,
            estimated_tokens=estimated_tokens,
            estimated_cost_usd=estimated_cost,
            token_budget_cap=payload.token_budget_cap,
            cost_budget_cap_usd=Decimal(str(payload.cost_budget_cap_usd)),
            ack_required=True,
            ack_confirmed=True,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        session.add(evaluation)
        await session.flush()
        eval_id = int(evaluation.id)
        await session.commit()

    redis = require_app_redis(request)
    await redis.enqueue_job("external_eval_prepass", eval_id)
    return {"ok": True, "external_eval_id": eval_id, "status": "queued"}


@router.get("")
async def list_external_evals(
    installation_id: int = Query(..., ge=1),
    limit: int = Query(default=25, ge=1, le=200),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> list[dict[str, object]]:
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, installation_id)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        rows = await session.scalars(
            select(ExternalEvaluation)
            .where(ExternalEvaluation.installation_id == installation_id)
            .order_by(ExternalEvaluation.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": int(row.id),
                "installation_id": int(row.installation_id),
                "repo_url": row.repo_url,
                "owner": row.owner,
                "repo": row.repo,
                "target_ref": row.target_ref,
                "status": row.status,
                "estimated_tokens": int(row.estimated_tokens),
                "estimated_cost_usd": str(row.estimated_cost_usd),
                "token_budget_cap": int(row.token_budget_cap),
                "cost_budget_cap_usd": str(row.cost_budget_cap_usd),
                "findings_count": int(row.findings_count),
                "tokens_used": int(row.tokens_used),
                "cost_usd": str(row.cost_usd),
                "summary": row.summary,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            }
            for row in rows
        ]


@router.get("/{external_eval_id}")
async def get_external_eval(
    external_eval_id: int,
    installation_id: int = Query(..., ge=1),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, installation_id)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        row = await session.get(ExternalEvaluation, external_eval_id)
        if row is None or int(row.installation_id) != installation_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External evaluation not found")
        shards = await session.scalars(
            select(ExternalEvaluationShard)
            .where(ExternalEvaluationShard.external_evaluation_id == row.id)
            .order_by(ExternalEvaluationShard.id.asc())
        )
        findings = await session.scalars(
            select(ExternalEvaluationFinding)
            .where(ExternalEvaluationFinding.external_evaluation_id == row.id)
            .order_by(ExternalEvaluationFinding.severity.asc(), ExternalEvaluationFinding.id.asc())
            .limit(200)
        )
        return {
            "id": int(row.id),
            "installation_id": int(row.installation_id),
            "repo_url": row.repo_url,
            "owner": row.owner,
            "repo": row.repo,
            "target_ref": row.target_ref,
            "status": row.status,
            "summary": row.summary,
            "estimated_tokens": int(row.estimated_tokens),
            "estimated_cost_usd": str(row.estimated_cost_usd),
            "tokens_used": int(row.tokens_used),
            "cost_usd": str(row.cost_usd),
            "findings_count": int(row.findings_count),
            "prepass_metadata": row.prepass_metadata,
            "shards": [
                {
                    "id": int(shard.id),
                    "shard_key": shard.shard_key,
                    "status": shard.status,
                    "model_tier": shard.model_tier,
                    "file_count": int(shard.file_count),
                    "findings_count": int(shard.findings_count),
                    "tokens_used": int(shard.tokens_used),
                    "cost_usd": str(shard.cost_usd),
                }
                for shard in shards
            ],
            "findings": [
                {
                    "id": int(finding.id),
                    "category": finding.category,
                    "severity": finding.severity,
                    "title": finding.title,
                    "message": finding.message,
                    "file_path": finding.file_path,
                    "line_start": finding.line_start,
                    "line_end": finding.line_end,
                    "evidence": finding.evidence,
                }
                for finding in findings
            ],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }


@router.post("/{external_eval_id}/cancel")
async def cancel_external_eval(
    external_eval_id: int,
    payload: ExternalEvalCancelRequest,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, payload.installation_id)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, payload.installation_id)
        row = await session.get(ExternalEvaluation, external_eval_id)
        if row is None or int(row.installation_id) != payload.installation_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External evaluation not found")
        if row.status in {"complete", "failed", "partial", "canceled"}:
            return {"ok": True, "external_eval_id": external_eval_id, "status": row.status}
        row.status = "canceled"
        row.completed_at = datetime.now(timezone.utc)
        row.summary = row.summary or "Canceled by user."
        await session.commit()
        return {"ok": True, "external_eval_id": external_eval_id, "status": "canceled"}

