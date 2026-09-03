"""Compatibility shim — delivery moved to ``app.delivery``; these names stay importable."""

from typing import Any

from app.agent.schema import Finding, ReviewResult
from app.github.client import GitHubClient


def _should_skip_empty_review_comment(result: ReviewResult) -> bool:
    from app.delivery.comments import should_skip_empty

    return should_skip_empty(result)


def format_finding(finding: Finding) -> str:
    from app.delivery.comments import format_finding_human

    return format_finding_human(finding)


def build_review_comment_payload(finding: Finding) -> dict[str, str | int]:
    """Build a single inline comment for POST .../pulls/{n}/reviews.

    Multi-line comments require start_line + line per GitHub API; omitting them
    causes validation errors on the review submission.
    """
    from app.delivery.comments import build_comment_payload

    return build_comment_payload(finding)


async def post_review(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    result: ReviewResult,
    *,
    request_changes_policy: str = "critical_only",
    existing_comments: list[dict[str, Any]] | None = None,
    review_id: int | None = None,
    installation_id: int | None = None,
) -> dict[str, object]:
    from app.delivery.comments import post_review_batched

    return await post_review_batched(
        gh,
        owner,
        repo,
        pr_number,
        head_sha,
        result,
        request_changes_policy=request_changes_policy,
        existing_comments=existing_comments,
        review_id=review_id,
        installation_id=installation_id,
    )
