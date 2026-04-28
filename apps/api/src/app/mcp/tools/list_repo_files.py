"""MCP tool: list files under a resolved repo ref."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
from app.review.external.errors import RepoAccessError
from app.review.external.models import FileDescriptor, RepoRef


class ListRepoFilesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_ref: RepoRef = Field(..., description="Repo ref produced by resolve_repo.")
    max_files: int | None = Field(default=None, ge=1, le=50_000)


class ListRepoFilesResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    file_count: int = 0
    files: list[FileDescriptor] = []
    total_bytes: int = 0
    error: str | None = None


async def list_repo_files_tool(
    request: ListRepoFilesRequest, *, ctx: MCPToolContext
) -> ListRepoFilesResult:
    max_files = request.max_files or ctx.config.max_files
    try:
        files = await ctx.source.list_files(request.repo_ref, max_files=max_files)
    except RepoAccessError as exc:
        return ListRepoFilesResult(ok=False, error=str(exc))
    total_bytes = sum(item.size_bytes for item in files)
    return ListRepoFilesResult(
        ok=True,
        file_count=len(files),
        files=files,
        total_bytes=total_bytes,
    )
