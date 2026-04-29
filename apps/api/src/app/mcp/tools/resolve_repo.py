"""MCP tool: resolve a public GitHub URL into a concrete ``RepoRef``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
from app.review.external.errors import RepoAccessError
from app.review.external.models import RepoRef


class ResolveRepoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str = Field(..., description="Public GitHub URL (https://github.com/owner/repo).")
    ref: str | None = Field(
        default=None,
        description="Optional branch, tag, or commit SHA; defaults to the default branch.",
    )


class ResolveRepoResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    repo_ref: RepoRef | None = None
    error: str | None = None


async def resolve_repo_tool(
    request: ResolveRepoRequest, *, ctx: MCPToolContext
) -> ResolveRepoResult:
    try:
        owner, repo = RepoRef.parse_url(request.repo_url)
    except ValueError as exc:
        return ResolveRepoResult(ok=False, error=str(exc))
    try:
        repo_ref = await ctx.source.resolve_ref(owner, repo, request.ref)
    except RepoAccessError as exc:
        return ResolveRepoResult(ok=False, error=str(exc))
    return ResolveRepoResult(ok=True, repo_ref=repo_ref)
