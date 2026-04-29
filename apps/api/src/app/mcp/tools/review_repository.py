"""MCP tool: end-to-end review of a public GitHub repository.

This is the autonomous-agent entry point: give it a URL, it resolves,
prepasses, shards, analyzes, and synthesizes findings in one call.
Prefer the fine-grained tools when the client wants to reason between
stages.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
from app.mcp.tools.estimate_review import build_ack_token
from app.review.external.errors import ReviewEngineError
from app.review.external.models import ReviewReport


class ReviewRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str = Field(
        ..., description="Public GitHub URL (https://github.com/owner/repo)."
    )
    ref: str | None = Field(
        default=None,
        description="Optional branch, tag, or commit SHA; defaults to the default branch.",
    )
    ack_token: str | None = Field(
        default=None,
        description=(
            "Acknowledgment token returned by estimate_review when ack_required=true."
        ),
    )


class ReviewRepositoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    report: ReviewReport | None = None
    ack_required: bool = False
    projected_tokens: int = Field(default=0, ge=0)
    projected_cost_usd: float = Field(default=0.0, ge=0.0)
    warning: str | None = None
    error: str | None = None


async def review_repository_tool(
    request: ReviewRepositoryRequest, *, ctx: MCPToolContext
) -> ReviewRepositoryResult:
    engine = ctx.build_engine()
    try:
        repo_ref, file_count, projected_tokens, projected_cost_usd, ack_required = (
            await engine.estimate_review(repo_url=request.repo_url, ref=request.ref)
        )
        if ack_required:
            expected_ack_token = build_ack_token(
                repo_ref=repo_ref,
                file_count=file_count,
                projected_tokens=projected_tokens,
                projected_cost_usd=projected_cost_usd,
            )
            if request.ack_token != expected_ack_token:
                return ReviewRepositoryResult(
                    ok=False,
                    ack_required=True,
                    projected_tokens=projected_tokens,
                    projected_cost_usd=projected_cost_usd,
                    warning=(
                        "Acknowledgment required before full-repo review. "
                        "Run estimate_review first and pass its ack_token."
                    ),
                    error="ack_required",
                )
        report = await engine.review(repo_url=request.repo_url, ref=request.ref)
    except ReviewEngineError as exc:
        return ReviewRepositoryResult(ok=False, error=str(exc))
    return ReviewRepositoryResult(
        ok=report.status != "failed",
        report=report,
        ack_required=ack_required,
        projected_tokens=projected_tokens,
        projected_cost_usd=projected_cost_usd,
    )
