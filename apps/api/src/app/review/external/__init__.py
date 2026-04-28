"""External repository review core.

Exposes the ``ReviewEngine`` orchestrator and its value types for use by
the FastAPI/ARQ wiring in ``app.agent.external.orchestrator`` and the MCP
server in ``app.mcp``. The package is deliberately free of database and
queue imports so it can be embedded in any process.
"""

from __future__ import annotations

from app.review.external.engine import ReviewEngine
from app.review.external.errors import (
    BudgetExceededError,
    RepoAccessError,
    ReviewEngineError,
    SourceError,
)
from app.review.external.models import (
    EngineConfig,
    FileDescriptor,
    Finding,
    FindingCategory,
    FindingSeverity,
    PrepassPlan,
    PrepassSignals,
    RepoRef,
    ReviewReport,
    RuleMatch,
    ServiceTier,
    Shard,
    ShardResult,
)
from app.review.external.sources.base import RepoSource
from app.review.external.sources.github import GitHubRepoSource
from app.review.external.sources.memory import InMemoryRepoSource

__all__ = [
    "BudgetExceededError",
    "EngineConfig",
    "FileDescriptor",
    "Finding",
    "FindingCategory",
    "FindingSeverity",
    "GitHubRepoSource",
    "InMemoryRepoSource",
    "PrepassPlan",
    "PrepassSignals",
    "RepoAccessError",
    "RepoRef",
    "RepoSource",
    "ReviewEngine",
    "ReviewEngineError",
    "ReviewReport",
    "RuleMatch",
    "ServiceTier",
    "Shard",
    "ShardResult",
    "SourceError",
]
