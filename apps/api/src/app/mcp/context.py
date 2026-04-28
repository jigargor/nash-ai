"""Shared execution context for MCP tools.

The server constructs a single :class:`MCPToolContext` per run and
passes it to every tool. This keeps HTTP client lifecycles under
control (one ``GitHubRepoSource`` with caching lives as long as the
server process) and makes dependency injection explicit for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.review.external.analyzer import RuleRegistry, default_registry
from app.review.external.engine import ReviewEngine
from app.review.external.models import EngineConfig
from app.review.external.sources.base import RepoSource
from app.review.external.sources.github import GitHubRepoSource


@dataclass
class MCPToolContext:
    """Bundle of shared resources given to every tool invocation."""

    source: RepoSource
    config: EngineConfig
    rules: RuleRegistry = field(default_factory=default_registry)

    def build_engine(self) -> ReviewEngine:
        return ReviewEngine(source=self.source, config=self.config, rules=self.rules)

    async def aclose(self) -> None:
        await self.source.aclose()


def build_default_context(
    *,
    config: EngineConfig | None = None,
    github_token: str | None = None,
) -> MCPToolContext:
    resolved_config = config or EngineConfig(github_token=github_token)
    source = GitHubRepoSource(
        github_token=resolved_config.github_token or github_token,
        timeout_seconds=resolved_config.http_timeout_seconds,
    )
    return MCPToolContext(source=source, config=resolved_config)
