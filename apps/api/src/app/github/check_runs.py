"""GitHub Check Run helpers for truthful PR-visible review status.

Requires the GitHub App permission ``checks: write``. When the permission is
missing or ``settings.enable_check_runs`` is False, helpers no-op and log.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.github.client import GitHubClient

logger = logging.getLogger(__name__)

CHECK_RUN_NAME = "Nash AI Review"


async def upsert_review_check_run(
    gh: GitHubClient,
    *,
    owner: str,
    repo: str,
    head_sha: str,
    status: str,
    conclusion: str | None = None,
    title: str,
    summary: str,
    check_run_id: int | None = None,
    external_id: str | None = None,
) -> int | None:
    """Create or update a check run. Returns the check run id, or None on failure/disabled."""
    if not settings.enable_check_runs:
        return None
    output = {"title": title[:255], "summary": summary[:65_535]}
    payload: dict[str, Any] = {
        "name": CHECK_RUN_NAME,
        "head_sha": head_sha,
        "status": status,
        "output": output,
    }
    if conclusion is not None:
        payload["conclusion"] = conclusion
    if external_id:
        payload["external_id"] = external_id[:64]
    try:
        if check_run_id is not None:
            result = await gh.patch_json(f"/repos/{owner}/{repo}/check-runs/{check_run_id}", payload)
        else:
            result = await gh.post_json(f"/repos/{owner}/{repo}/check-runs", payload)
        raw_id = result.get("id")
        return int(raw_id) if isinstance(raw_id, int) else None
    except Exception as exc:
        logger.info(
            "Check run upsert skipped/failed owner=%s repo=%s sha=%s status=%s err=%s",
            owner,
            repo,
            head_sha[:8] if head_sha else "",
            status,
            exc.__class__.__name__,
        )
        return None


def conclusion_for_review_status(review_status: str) -> tuple[str, str | None]:
    """Map internal review status to (check_status, conclusion)."""
    normalized = review_status.strip().lower()
    if normalized in {"queued"}:
        return "queued", None
    if normalized in {"running"}:
        return "in_progress", None
    if normalized in {"done"}:
        return "completed", "success"
    if normalized in {"partial"}:
        return "completed", "neutral"
    if normalized in {"skipped", "rate_limited", "budget_exhausted", "canceled", "superseded"}:
        return "completed", "neutral"
    return "completed", "failure"
