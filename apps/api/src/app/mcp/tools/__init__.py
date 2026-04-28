"""Tool implementations registered on the external-review MCP server.

Each module owns one tool, defines its Pydantic request/response models,
and calls into :mod:`app.review.external`. Separating tools into their
own modules keeps the surface testable in isolation and makes adding
new tools a purely additive change.
"""

from __future__ import annotations

from app.mcp.tools.analyze_file import AnalyzeFileRequest, AnalyzeFileResult, analyze_file_tool
from app.mcp.tools.fetch_file_sample import (
    FetchFileSampleRequest,
    FetchFileSampleResult,
    fetch_file_sample_tool,
)
from app.mcp.tools.list_repo_files import (
    ListRepoFilesRequest,
    ListRepoFilesResult,
    list_repo_files_tool,
)
from app.mcp.tools.plan_shards import (
    PlanShardsRequest,
    PlanShardsResult,
    plan_shards_tool,
)
from app.mcp.tools.resolve_repo import (
    ResolveRepoRequest,
    ResolveRepoResult,
    resolve_repo_tool,
)
from app.mcp.tools.review_repository import (
    ReviewRepositoryRequest,
    ReviewRepositoryResult,
    review_repository_tool,
)
from app.mcp.tools.run_prepass import (
    RunPrepassRequest,
    RunPrepassResult,
    run_prepass_tool,
)
from app.mcp.tools.synthesize_findings import (
    SynthesizeFindingsRequest,
    SynthesizeFindingsResult,
    synthesize_findings_tool,
)

__all__ = [
    "AnalyzeFileRequest",
    "AnalyzeFileResult",
    "FetchFileSampleRequest",
    "FetchFileSampleResult",
    "ListRepoFilesRequest",
    "ListRepoFilesResult",
    "PlanShardsRequest",
    "PlanShardsResult",
    "ResolveRepoRequest",
    "ResolveRepoResult",
    "ReviewRepositoryRequest",
    "ReviewRepositoryResult",
    "RunPrepassRequest",
    "RunPrepassResult",
    "SynthesizeFindingsRequest",
    "SynthesizeFindingsResult",
    "analyze_file_tool",
    "fetch_file_sample_tool",
    "list_repo_files_tool",
    "plan_shards_tool",
    "resolve_repo_tool",
    "review_repository_tool",
    "run_prepass_tool",
    "synthesize_findings_tool",
]
