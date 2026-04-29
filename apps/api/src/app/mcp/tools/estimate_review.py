"""MCP tool: estimate full-review scope, budget, and acknowledgment needs."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
from app.review.external.errors import ReviewEngineError
from app.review.external.models import RepoRef


def build_ack_token(
    *, repo_ref: RepoRef, file_count: int, projected_tokens: int, projected_cost_usd: float
) -> str:
    payload = (
        f"{repo_ref.owner}/{repo_ref.repo}:{repo_ref.ref}:"
        f"{file_count}:{projected_tokens}:{projected_cost_usd:.6f}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EstimateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str = Field(
        ..., description="Public GitHub URL (https://github.com/owner/repo)."
    )
    ref: str | None = Field(
        default=None,
        description="Optional branch, tag, or commit SHA; defaults to the default branch.",
    )


class EstimateReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    repo_ref: RepoRef | None = None
    file_count: int = Field(default=0, ge=0)
    projected_tokens: int = Field(default=0, ge=0)
    projected_cost_usd: float = Field(default=0.0, ge=0.0)
    ack_required: bool = False
    ack_token: str | None = None
    warning: str | None = None
    error: str | None = None


async def estimate_review_tool(
    request: EstimateReviewRequest, *, ctx: MCPToolContext
) -> EstimateReviewResult:
    engine = ctx.build_engine()
    try:
        repo_ref, file_count, projected_tokens, projected_cost_usd, ack_required = (
            await engine.estimate_review(repo_url=request.repo_url, ref=request.ref)
        )
    except ReviewEngineError as exc:
        return EstimateReviewResult(ok=False, error=str(exc))

    warning: str | None = None
    ack_token: str | None = None
    if ack_required:
        warning = (
            "Full-repo evaluation can be expensive. Run review_repository only after "
            "explicit acknowledgment."
        )
        ack_token = build_ack_token(
            repo_ref=repo_ref,
            file_count=file_count,
            projected_tokens=projected_tokens,
            projected_cost_usd=projected_cost_usd,
        )

    return EstimateReviewResult(
        ok=True,
        repo_ref=repo_ref,
        file_count=file_count,
        projected_tokens=projected_tokens,
        projected_cost_usd=projected_cost_usd,
        ack_required=ack_required,
        ack_token=ack_token,
        warning=warning,
    )
