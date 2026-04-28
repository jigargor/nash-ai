"""MCP tool: run the pattern analyzer over a single file."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.context import MCPToolContext
from app.review.external.analyzer import analyze_file
from app.review.external.models import Finding, RuleMatch


class AnalyzeFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1, max_length=4_096)
    content: str = Field(..., max_length=500_000)


class AnalyzeFileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    matches: list[RuleMatch] = []
    findings: list[Finding] = []


async def analyze_file_tool(
    request: AnalyzeFileRequest, *, ctx: MCPToolContext
) -> AnalyzeFileResult:
    matches = analyze_file(request.path, request.content, registry=ctx.rules)
    findings = [Finding.from_rule_match(match) for match in matches]
    return AnalyzeFileResult(ok=True, matches=matches, findings=findings)
