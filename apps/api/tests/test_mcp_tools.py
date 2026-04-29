from __future__ import annotations

import asyncio

import pytest

from app.mcp.context import MCPToolContext
from app.mcp.server import build_mcp_app
from app.mcp.tools import (
    AnalyzeFileRequest,
    EstimateReviewRequest,
    FetchFileSampleRequest,
    ListRepoFilesRequest,
    PlanShardsRequest,
    ResolveRepoRequest,
    ReviewRepositoryRequest,
    RunPrepassRequest,
    SynthesizeFindingsRequest,
    analyze_file_tool,
    estimate_review_tool,
    fetch_file_sample_tool,
    list_repo_files_tool,
    plan_shards_tool,
    resolve_repo_tool,
    review_repository_tool,
    run_prepass_tool,
    synthesize_findings_tool,
)
from app.review.external import EngineConfig, InMemoryRepoSource


_SOURCE_FILES = {
    "src/auth.py": (
        "def run(user_input):\n    eval(user_input)\n"
    ),
    "README.md": "Hello.",
    "assets/logo.svg": "<svg/>",
}


def _build_ctx() -> MCPToolContext:
    source = InMemoryRepoSource(
        owner="octocat",
        repo="repo",
        default_branch="main",
        refs={"main": _SOURCE_FILES},
    )
    return MCPToolContext(source=source, config=EngineConfig(prepass_sample_limit=10))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_build_mcp_app_registers_every_tool() -> None:
    app, ctx = build_mcp_app(context=_build_ctx())
    try:
        tools = asyncio.run(app.list_tools())
        tool_names = {tool.name for tool in tools}
        assert tool_names == {
            "resolve_repo",
            "list_repo_files",
            "estimate_review",
            "run_prepass",
            "plan_shards",
            "fetch_file_sample",
            "analyze_file",
            "synthesize_findings",
            "review_repository",
        }
    finally:
        asyncio.run(ctx.aclose())


@pytest.mark.anyio
async def test_resolve_and_list_repo_files() -> None:
    ctx = _build_ctx()
    try:
        resolved = await resolve_repo_tool(
            ResolveRepoRequest(repo_url="https://github.com/octocat/repo"), ctx=ctx
        )
        assert resolved.ok
        assert resolved.repo_ref is not None
        assert resolved.repo_ref.ref == "main"
        listing = await list_repo_files_tool(
            ListRepoFilesRequest(repo_ref=resolved.repo_ref), ctx=ctx
        )
        assert listing.ok
        assert listing.file_count == len(_SOURCE_FILES)
        assert listing.total_bytes > 0
    finally:
        await ctx.aclose()


@pytest.mark.anyio
async def test_resolve_invalid_url_returns_error() -> None:
    ctx = _build_ctx()
    try:
        result = await resolve_repo_tool(
            ResolveRepoRequest(repo_url="https://gitlab.com/a/b"), ctx=ctx
        )
        assert result.ok is False
        assert result.error
    finally:
        await ctx.aclose()


@pytest.mark.anyio
async def test_run_prepass_and_plan_shards() -> None:
    ctx = _build_ctx()
    try:
        resolved = await resolve_repo_tool(
            ResolveRepoRequest(repo_url="https://github.com/octocat/repo"), ctx=ctx
        )
        assert resolved.repo_ref is not None
        listing = await list_repo_files_tool(
            ListRepoFilesRequest(repo_ref=resolved.repo_ref), ctx=ctx
        )
        prepass = await run_prepass_tool(
            RunPrepassRequest(repo_ref=resolved.repo_ref, files=listing.files),
            ctx=ctx,
        )
        assert prepass.ok
        assert prepass.plan is not None
        assert prepass.plan.shard_count >= 1
        shards = await plan_shards_tool(
            PlanShardsRequest(files=listing.files, plan=prepass.plan),
            ctx=ctx,
        )
        assert shards.ok
        assert shards.shards
    finally:
        await ctx.aclose()


@pytest.mark.anyio
async def test_fetch_file_sample_returns_content() -> None:
    ctx = _build_ctx()
    try:
        resolved = await resolve_repo_tool(
            ResolveRepoRequest(repo_url="https://github.com/octocat/repo"), ctx=ctx
        )
        assert resolved.repo_ref is not None
        sample = await fetch_file_sample_tool(
            FetchFileSampleRequest(
                repo_ref=resolved.repo_ref,
                path="src/auth.py",
                max_bytes=4096,
            ),
            ctx=ctx,
        )
        assert sample.ok
        assert "eval" in sample.content
    finally:
        await ctx.aclose()


@pytest.mark.anyio
async def test_analyze_file_produces_findings() -> None:
    ctx = _build_ctx()
    try:
        analysis = await analyze_file_tool(
            AnalyzeFileRequest(
                path="src/auth.py",
                content=_SOURCE_FILES["src/auth.py"],
            ),
            ctx=ctx,
        )
        assert analysis.ok
        assert analysis.findings
        assert analysis.findings[0].category == "security"
    finally:
        await ctx.aclose()


@pytest.mark.anyio
async def test_synthesize_findings_filters_weak_evidence() -> None:
    ctx = _build_ctx()
    try:
        analysis = await analyze_file_tool(
            AnalyzeFileRequest(
                path="src/auth.py",
                content=_SOURCE_FILES["src/auth.py"],
            ),
            ctx=ctx,
        )
        result = await synthesize_findings_tool(
            SynthesizeFindingsRequest(findings=analysis.findings), ctx=ctx
        )
        assert result.ok
        assert result.kept_count >= 1
    finally:
        await ctx.aclose()


@pytest.mark.anyio
async def test_review_repository_end_to_end() -> None:
    ctx = _build_ctx()
    try:
        estimate = await estimate_review_tool(
            EstimateReviewRequest(repo_url="https://github.com/octocat/repo"),
            ctx=ctx,
        )
        assert estimate.ok
        result = await review_repository_tool(
            ReviewRepositoryRequest(
                repo_url="https://github.com/octocat/repo",
                ack_token=estimate.ack_token,
            ),
            ctx=ctx,
        )
        assert result.ok
        assert result.report is not None
        assert result.report.findings
        assert all(
            finding.severity in {"critical", "high"}
            for finding in result.report.findings
        )
    finally:
        await ctx.aclose()


@pytest.mark.anyio
async def test_review_repository_requires_ack_when_threshold_exceeded() -> None:
    source = InMemoryRepoSource(
        owner="octocat",
        repo="repo",
        default_branch="main",
        refs={"main": _SOURCE_FILES},
    )
    ctx = MCPToolContext(
        source=source,
        config=EngineConfig(
            prepass_sample_limit=10,
            ack_required_token_threshold=1_000,
            ack_required_cost_threshold_usd=0.00001,
        ),
    )
    try:
        result = await review_repository_tool(
            ReviewRepositoryRequest(repo_url="https://github.com/octocat/repo"),
            ctx=ctx,
        )
        assert result.ok is False
        assert result.ack_required is True
        assert result.error == "ack_required"
    finally:
        await ctx.aclose()
