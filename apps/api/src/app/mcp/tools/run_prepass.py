"""MCP tool: run the cheap deterministic prepass over a repo tree."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
from app.review.external.models import (
    FileDescriptor,
    PrepassPlan,
    PrepassSignals,
    RepoRef,
)


class RunPrepassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_ref: RepoRef
    files: list[FileDescriptor] = Field(
        ...,
        description="File list from list_repo_files; the prepass uses bounded sampling.",
    )
    sample_limit: int | None = Field(default=None, ge=0, le=2_000)


class RunPrepassResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    signals: PrepassSignals | None = None
    plan: PrepassPlan | None = None
    error: str | None = None


async def run_prepass_tool(
    request: RunPrepassRequest, *, ctx: MCPToolContext
) -> RunPrepassResult:
    engine = ctx.build_engine()
    signals, plan = await engine.prepass(
        request.repo_ref,
        request.files,
        sample_limit=request.sample_limit,
    )
    return RunPrepassResult(ok=True, signals=signals, plan=plan)
