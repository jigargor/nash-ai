"""Structured error hierarchy for the review engine.

Subclasses give callers a stable contract for programmatic handling
(HTTP status mapping, MCP error envelopes, retry classification) while
preserving human-readable messages.
"""

from __future__ import annotations


class ReviewEngineError(RuntimeError):
    """Base class for every error raised by the review engine."""


class SourceError(ReviewEngineError):
    """Raised when a repository source cannot fulfill a request."""


class RepoAccessError(SourceError):
    """Raised when a repository URL or ref cannot be resolved."""


class BudgetExceededError(ReviewEngineError):
    """Raised when token or cost budgets would be exceeded by the next step."""

    def __init__(self, *, kind: str, limit: float, projected: float) -> None:
        super().__init__(
            f"Budget exceeded for {kind}: projected={projected} limit={limit}"
        )
        self.kind = kind
        self.limit = limit
        self.projected = projected
