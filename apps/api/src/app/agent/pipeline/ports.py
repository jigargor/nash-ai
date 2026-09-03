"""Pipeline ports — worker and harness inject concrete implementations."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.agent.schema import ReviewResult


@runtime_checkable
class GitHubReader(Protocol):
    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]: ...

    async def get_pull_request_diff(self, owner: str, repo: str, pr_number: int) -> str: ...

    async def get_pull_request_commits(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]: ...

    async def get_file_content(
        self, owner: str, repo: str, path: str, ref: str
    ) -> str: ...

    async def get_pr_reviews_by_bot(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]: ...


class DeliveryResult(dict[str, Any]):
    """Loose dict compatible with GitHub review POST response."""


@runtime_checkable
class DeliverySink(Protocol):
    async def post(
        self,
        result: ReviewResult,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
    ) -> DeliveryResult: ...


@runtime_checkable
class Persistence(Protocol):
    async def mark_running(self, review_id: int, installation_id: int) -> None: ...

    async def mark_done(
        self,
        *,
        review_id: int,
        installation_id: int,
        result: ReviewResult,
        status: str,
        tokens_used: int,
        cost_usd: float | None,
        debug_artifacts: dict[str, Any] | None = None,
    ) -> None: ...

    async def seed_outcomes(
        self,
        *,
        review_id: int,
        installation_id: int,
        finding_count: int,
        github_comment_ids: list[int | None],
    ) -> None: ...
