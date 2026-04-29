"""MCP tool: fetch a bounded UTF-8 sample of a single file."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
from app.review.external.models import RepoRef


class FetchFileSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_ref: RepoRef
    path: str = Field(..., min_length=1, max_length=4_096)
    max_bytes: int | None = Field(default=None, ge=256, le=200_000)


class FetchFileSampleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    path: str
    bytes_returned: int = 0
    content: str = ""


async def fetch_file_sample_tool(
    request: FetchFileSampleRequest, *, ctx: MCPToolContext
) -> FetchFileSampleResult:
    max_bytes = request.max_bytes or ctx.config.analyze_sample_bytes
    content = await ctx.source.fetch_file(
        request.repo_ref, request.path, max_bytes=max_bytes
    )
    return FetchFileSampleResult(
        ok=True,
        path=request.path,
        bytes_returned=len(content.encode("utf-8")),
        content=content,
    )
