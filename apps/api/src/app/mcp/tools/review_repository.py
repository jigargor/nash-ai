"""MCP tool: end-to-end review of a public GitHub repository.

This is the autonomous-agent entry point: give it a URL, it resolves,
prepasses, shards, analyzes, and synthesizes findings in one call.
Prefer the fine-grained tools when the client wants to reason between
stages.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
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


class ReviewRepositoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    report: ReviewReport | None = None
    error: str | None = None


async def review_repository_tool(
    request: ReviewRepositoryRequest, *, ctx: MCPToolContext
) -> ReviewRepositoryResult:
    engine = ctx.build_engine()
    try:
        report = await engine.review(repo_url=request.repo_url, ref=request.ref)
    except ReviewEngineError as exc:
        return ReviewRepositoryResult(ok=False, error=str(exc))
    return ReviewRepositoryResult(ok=report.status != "failed", report=report)
