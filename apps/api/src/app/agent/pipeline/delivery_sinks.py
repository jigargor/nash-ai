"""Dry-run and live delivery sinks for the review pipeline."""

from __future__ import annotations

from typing import Any

from app.agent.pipeline.ports import DeliveryResult
from app.agent.schema import ReviewResult
from app.delivery.ids import assign_finding_ids

__all__ = ["DryRunDeliverySink", "LiveDeliverySink", "assign_finding_ids"]


class DryRunDeliverySink:
    """Renders comment bodies without posting to GitHub."""

    def __init__(self) -> None:
        self.rendered: list[dict[str, Any]] = []
        self.summary: str = ""
        self.event: str = "COMMENT"

    async def post(
        self,
        result: ReviewResult,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
    ) -> DeliveryResult:
        from app.delivery.comments import build_comment_payload, format_finding_human, review_event_for

        self.summary = result.summary
        self.event = review_event_for(result, "critical_only")
        self.rendered = [
            {
                **build_comment_payload(finding),
                "formatted_body": format_finding_human(finding),
                "finding_id": finding.finding_id,
            }
            for finding in result.findings
        ]
        return DeliveryResult(
            {
                "dry_run": True,
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "commit_sha": commit_sha,
                "event": self.event,
                "comments": self.rendered,
                "body": result.summary,
            }
        )

    def render_markdown(self) -> str:
        lines = [f"# Review summary ({self.event})\n\n{self.summary}\n"]
        for idx, comment in enumerate(self.rendered, start=1):
            path = comment.get("path", "?")
            line = comment.get("line", "?")
            body = comment.get("formatted_body") or comment.get("body", "")
            lines.append(f"## Finding {idx}: `{path}`:{line}\n\n{body}\n")
        return "\n".join(lines)


class LiveDeliverySink:
    """Posts via GitHub Reviews API (batched, per-comment 422 fallback)."""

    def __init__(
        self,
        github_client: Any,
        *,
        request_changes_policy: str = "critical_only",
        review_id: int | None = None,
        installation_id: int | None = None,
    ) -> None:
        self._gh = github_client
        self._policy = request_changes_policy
        self._review_id = review_id
        self._installation_id = installation_id

    async def post(
        self,
        result: ReviewResult,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
    ) -> DeliveryResult:
        from app.delivery.comments import post_review_batched

        existing: list[dict[str, Any]] | None = None
        getter = getattr(self._gh, "get_pr_reviews_by_bot", None)
        if callable(getter):
            try:
                existing = await getter(owner, repo, pr_number)
            except Exception:
                existing = None
        response = await post_review_batched(
            self._gh,
            owner,
            repo,
            pr_number,
            commit_sha,
            result,
            request_changes_policy=self._policy,
            existing_comments=existing,
            review_id=self._review_id,
            installation_id=self._installation_id,
        )
        return DeliveryResult(response if isinstance(response, dict) else {})
