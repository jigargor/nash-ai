"""FastMCP application wiring for the external-review MCP server.

The module exposes :func:`build_mcp_app`, which returns a configured
``FastMCP`` instance with every tool pre-registered. Running it as a
script starts either an stdio (default) or streamable-HTTP server.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Literal

from mcp.server.fastmcp import FastMCP

from app.mcp.context import MCPToolContext, build_default_context
from app.mcp.tools import (
    AnalyzeFileRequest,
    AnalyzeFileResult,
    FetchFileSampleRequest,
    FetchFileSampleResult,
    ListRepoFilesRequest,
    ListRepoFilesResult,
    PlanShardsRequest,
    PlanShardsResult,
    ResolveRepoRequest,
    ResolveRepoResult,
    ReviewRepositoryRequest,
    ReviewRepositoryResult,
    RunPrepassRequest,
    RunPrepassResult,
    SynthesizeFindingsRequest,
    SynthesizeFindingsResult,
    analyze_file_tool,
    fetch_file_sample_tool,
    list_repo_files_tool,
    plan_shards_tool,
    resolve_repo_tool,
    review_repository_tool,
    run_prepass_tool,
    synthesize_findings_tool,
)
from app.review.external.models import EngineConfig

_LOGGER = logging.getLogger(__name__)

TransportMode = Literal["stdio", "http"]


def build_mcp_app(
    *,
    context: MCPToolContext | None = None,
    name: str = "codereview-external",
) -> tuple[FastMCP, MCPToolContext]:
    """Build a ``FastMCP`` instance with every tool registered.

    Returns the app and the owning context so callers can close the
    underlying HTTP client when the server shuts down.
    """

    ctx = context or build_default_context()
    app = FastMCP(
        name,
        instructions=(
            "Tools for reviewing public GitHub repositories with a staged,"
            " audit-friendly pipeline. Start with resolve_repo + list_repo_files,"
            " then run_prepass, plan_shards, fetch_file_sample, analyze_file, and"
            " synthesize_findings. Use review_repository for an autonomous"
            " end-to-end review."
        ),
    )

    @app.tool(
        name="resolve_repo",
        description=(
            "Resolve a public GitHub URL into a concrete owner/repo/ref/default_branch."
        ),
        structured_output=True,
    )
    async def _resolve_repo(request: ResolveRepoRequest) -> ResolveRepoResult:
        return await resolve_repo_tool(request, ctx=ctx)

    @app.tool(
        name="list_repo_files",
        description=(
            "List blob files under a resolved RepoRef. Returns a bounded list"
            " honouring max_files."
        ),
        structured_output=True,
    )
    async def _list_repo_files(request: ListRepoFilesRequest) -> ListRepoFilesResult:
        return await list_repo_files_tool(request, ctx=ctx)

    @app.tool(
        name="run_prepass",
        description=(
            "Run the deterministic prepass over a file list, returning risk"
            " signals and a recommended shard plan."
        ),
        structured_output=True,
    )
    async def _run_prepass(request: RunPrepassRequest) -> RunPrepassResult:
        return await run_prepass_tool(request, ctx=ctx)

    @app.tool(
        name="plan_shards",
        description=(
            "Distribute files into balanced shards using the prepass plan and"
            " an optional exclusion list."
        ),
        structured_output=True,
    )
    async def _plan_shards(request: PlanShardsRequest) -> PlanShardsResult:
        return await plan_shards_tool(request, ctx=ctx)

    @app.tool(
        name="fetch_file_sample",
        description=(
            "Fetch a bounded UTF-8 sample of a single file at a resolved repo ref."
        ),
        structured_output=True,
    )
    async def _fetch_file_sample(
        request: FetchFileSampleRequest,
    ) -> FetchFileSampleResult:
        return await fetch_file_sample_tool(request, ctx=ctx)

    @app.tool(
        name="analyze_file",
        description=(
            "Run the pattern analyzer over a file's content and return rule"
            " matches plus structured findings."
        ),
        structured_output=True,
    )
    async def _analyze_file(request: AnalyzeFileRequest) -> AnalyzeFileResult:
        return await analyze_file_tool(request, ctx=ctx)

    @app.tool(
        name="synthesize_findings",
        description=(
            "Filter, dedupe, and rank candidate findings into the final"
            " critical-only output."
        ),
        structured_output=True,
    )
    async def _synthesize_findings(
        request: SynthesizeFindingsRequest,
    ) -> SynthesizeFindingsResult:
        return await synthesize_findings_tool(request, ctx=ctx)

    @app.tool(
        name="review_repository",
        description=(
            "End-to-end pipeline: resolve + list + prepass + shard + analyze"
            " + synthesize for a public GitHub URL."
        ),
        structured_output=True,
    )
    async def _review_repository(
        request: ReviewRepositoryRequest,
    ) -> ReviewRepositoryResult:
        return await review_repository_tool(request, ctx=ctx)

    return app, ctx


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="External review MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport to expose (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8787")),
    )
    return parser.parse_args(argv)


async def _run_http(app: FastMCP, host: str, port: int) -> None:
    app.settings.host = host
    app.settings.port = port
    await app.run_streamable_http_async()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    app, ctx = build_mcp_app()
    try:
        if args.transport == "stdio":
            asyncio.run(app.run_stdio_async())
        else:
            _LOGGER.info(
                "Starting external-review MCP server via streamable HTTP on %s:%s",
                args.host,
                args.port,
            )
            asyncio.run(_run_http(app, args.host, args.port))
    finally:
        asyncio.run(ctx.aclose())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
