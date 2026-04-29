"""MCP tool: filter, dedupe, and rank a list of candidate findings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.mcp.context import MCPToolContext
from app.review.external.models import Finding
from app.review.external.synthesis import synthesize


class SynthesizeFindingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]


class SynthesizeFindingsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    kept_count: int
    findings: list[Finding]


async def synthesize_findings_tool(
    request: SynthesizeFindingsRequest, *, ctx: MCPToolContext
) -> SynthesizeFindingsResult:
    _ = ctx
    kept = synthesize(request.findings)
    return SynthesizeFindingsResult(
        ok=True,
        kept_count=len(kept),
        findings=kept,
    )
