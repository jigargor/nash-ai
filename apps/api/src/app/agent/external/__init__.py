"""Legacy entry point that now re-exports the core review engine.

New code should import from ``app.review.external``; this package is
kept in place so existing call sites (``app.queue.worker``,
``app.api.external_evals``, tests) continue to work without churn.
"""

from __future__ import annotations

from app.review.external import (
    EngineConfig,
    FileDescriptor as ExternalFileDescriptor,
    Finding,
    GitHubRepoSource,
    InMemoryRepoSource,
    PrepassPlan,
    PrepassSignals,
    RepoRef,
    ReviewEngine,
    ReviewReport,
    RuleMatch,
    Shard,
    ShardResult,
)

__all__ = [
    "EngineConfig",
    "ExternalFileDescriptor",
    "Finding",
    "GitHubRepoSource",
    "InMemoryRepoSource",
    "PrepassPlan",
    "PrepassSignals",
    "RepoRef",
    "ReviewEngine",
    "ReviewReport",
    "RuleMatch",
    "Shard",
    "ShardResult",
]
