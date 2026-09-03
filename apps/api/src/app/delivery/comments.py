"""Human-style GitHub review delivery with batching and per-comment fallback."""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.agent.schema import Finding, ReviewResult
from app.delivery.ids import assign_finding_ids
from app.agent.text_sanitizer import sanitize_markdown_text, truncate_markdown_text
from app.github.client import GitHubClient

logger = logging.getLogger(__name__)

GITHUB_COMMENT_BATCH = 80
RequestChangesPolicy = Literal["critical_only", "high_or_above", "never", "always"]
REQUEST_CHANGES_POLICIES: frozenset[str] = frozenset(
    {"critical_only", "high_or_above", "never", "always"}
)


def nash_marker(finding_id: str | None) -> str:
    fid = finding_id or "unknown"
    return f"<!-- nash:f:{fid} -->"


def format_finding_human(finding: Finding, *, include_severity_label: bool = True) -> str:
    message = sanitize_markdown_text(finding.message)
    if include_severity_label:
        body = f"**{finding.severity}** — {message}"
    else:
        body = message
    body = f"{body}\n\n{nash_marker(finding.finding_id)}"
    if finding.suggestion:
        body = f"{body}\n\n```suggestion\n{finding.suggestion}\n```"
    return body


def build_comment_payload(finding: Finding) -> dict[str, str | int]:
    line_end = finding.line_end or finding.line_start
    payload: dict[str, str | int] = {
        "path": finding.file_path,
        "line": line_end,
        "side": finding.side,
        "body": format_finding_human(finding),
    }
    if finding.line_end is not None and finding.line_start < finding.line_end:
        payload["start_line"] = finding.line_start
        payload["start_side"] = finding.start_side or finding.side
    return payload


def should_skip_empty(result: ReviewResult) -> bool:
    if result.findings:
        return False
    summary = (result.summary or "").strip().lower()
    if not summary:
        return True
    return (
        "no chunk summaries were available for synthesis" in summary
        or ("chunked review coverage:" in summary and "no findings generated." in summary)
    )


def review_event_for(result: ReviewResult, policy: str) -> str:
    if policy == "never":
        return "COMMENT"
    if policy == "always":
        return "REQUEST_CHANGES"
    if policy == "high_or_above":
        if any(finding.severity in {"critical", "high"} for finding in result.findings):
            return "REQUEST_CHANGES"
        return "COMMENT"
    if any(finding.severity == "critical" for finding in result.findings):
        return "REQUEST_CHANGES"
    return "COMMENT"


def finding_key(finding: Finding) -> tuple[str, int, str]:
    return (finding.file_path, finding.line_start, finding.category)


async def post_review_batched(
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
    if should_skip_empty(result):
        logger.info("Skipping empty review for %s/%s#%s", owner, repo, pr_number)
        return {}

    findings = assign_finding_ids(list(result.findings))
    skipped_duplicates = 0
    if existing_comments:
        from app.delivery.synchronize import filter_new_findings

        before = len(findings)
        findings = filter_new_findings(findings, existing_comments)
        skipped_duplicates = before - len(findings)
        if skipped_duplicates:
            logger.info(
                "synchronize: skipped %s already-posted findings for %s/%s#%s",
                skipped_duplicates,
                owner,
                repo,
                pr_number,
            )
    result = ReviewResult(findings=findings, summary=result.summary)
    if not findings and skipped_duplicates:
        return {"rejected": [], "comment_ids": [], "skipped_duplicates": skipped_duplicates}

    event = review_event_for(result, request_changes_policy)
    rejected: list[dict[str, object]] = []
    posted_ids: list[int | None] = []
    github_response: dict[str, object] = {}

    remaining = list(findings)
    first = True
    while remaining:
        batch = remaining[:GITHUB_COMMENT_BATCH]
        remaining = remaining[GITHUB_COMMENT_BATCH:]
        comments = [build_comment_payload(finding) for finding in batch]
        payload: dict[str, object] = {
            "commit_id": head_sha,
            "body": truncate_markdown_text(result.summary, 1000) if first else "",
            "event": event if first else "COMMENT",
            "comments": comments,
        }
        first = False
        try:
            response = await gh.post_json(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", payload
            )
            if isinstance(response, dict):
                if not github_response:
                    github_response = dict(response)
                posted_ids.extend(_comment_ids_from_response(response))
            continue
        except Exception as batch_exc:
            logger.warning("Batch review post failed; falling back per comment: %s", batch_exc)

        # Per-comment fallback: post one-comment reviews, skip the ones GitHub rejects (422).
        for finding in batch:
            single: dict[str, object] = {
                "commit_id": head_sha,
                "body": "",
                "event": "COMMENT",
                "comments": [build_comment_payload(finding)],
            }
            try:
                response = await gh.post_json(
                    f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", single
                )
                if isinstance(response, dict):
                    if not github_response:
                        github_response = dict(response)
                    ids = _comment_ids_from_response(response)
                    posted_ids.extend(ids or [None])
            except Exception as exc:
                logger.warning(
                    "delivery.rejected path=%s line=%s err=%s",
                    finding.file_path,
                    finding.line_start,
                    exc,
                )
                posted_ids.append(None)
                rejected.append(
                    {
                        "file_path": finding.file_path,
                        "line_start": finding.line_start,
                        "finding_id": finding.finding_id,
                        "error": str(exc)[:300],
                    }
                )
                _emit_delivery_rejected(
                    review_id=review_id,
                    installation_id=installation_id,
                    finding=finding,
                    error_class=exc.__class__.__name__,
                )

    merged: dict[str, object] = dict(github_response)
    merged["rejected"] = rejected
    merged["comment_ids"] = posted_ids
    merged["skipped_duplicates"] = skipped_duplicates
    merged["event"] = event
    return merged


def _comment_ids_from_response(response: dict[str, object]) -> list[int | None]:
    comments_out = response.get("comments") or []
    ids: list[int | None] = []
    if isinstance(comments_out, list):
        for item in comments_out:
            if isinstance(item, dict):
                raw_id = item.get("id")
                ids.append(raw_id if isinstance(raw_id, int) else None)
    return ids


def _emit_delivery_rejected(
    *,
    review_id: int | None,
    installation_id: int | None,
    finding: Finding,
    error_class: str,
) -> None:
    if review_id is None or installation_id is None:
        return
    try:
        from app.observability import get_observer

        get_observer().record_delivery_rejected(
            review_id=review_id,
            installation_id=installation_id,
            file_path=finding.file_path,
            line_start=finding.line_start,
            error_class=error_class,
        )
    except Exception:  # pragma: no cover - telemetry must never break delivery
        logger.debug("delivery.rejected telemetry failed", exc_info=True)
