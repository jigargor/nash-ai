"""MCP tool: build balanced shards from prepass output."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
from app.review.external.models import FileDescriptor, PrepassPlan, Shard


class PlanShardsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[FileDescriptor]
    plan: PrepassPlan
    excluded_paths: list[str] = Field(default_factory=list)


class PlanShardsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    shards: list[Shard] = []


async def plan_shards_tool(
    request: PlanShardsRequest, *, ctx: MCPToolContext
) -> PlanShardsResult:
    engine = ctx.build_engine()
    shards = engine.plan_shards(
        request.files,
        request.plan,
        excluded_paths=set(request.excluded_paths),
    )
    return PlanShardsResult(ok=True, shards=shards)
