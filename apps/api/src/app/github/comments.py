from app.agent.schema import Finding, ReviewResult
from app.agent.text_sanitizer import sanitize_markdown_text, truncate_markdown_text
from app.github.client import GitHubClient


def format_finding(finding: Finding) -> str:
    message = sanitize_markdown_text(finding.message)
    body = (
        f"**{finding.severity} · {finding.category}** · confidence {finding.confidence}%\n\n"
        f"{message}"
    )
    if finding.suggestion:
        body = f"{body}\n\n```suggestion\n{finding.suggestion}\n```"
    return body


def build_review_comment_payload(finding: Finding) -> dict[str, str | int]:
    """Build a single inline comment for POST .../pulls/{n}/reviews.

    Multi-line comments require start_line + line per GitHub API; omitting them
    causes validation errors on the review submission.
    """
    line_end = finding.line_end or finding.line_start
    payload: dict[str, str | int] = {
        "path": finding.file_path,
        "line": line_end,
        "side": finding.side,
        "body": format_finding(finding),
    }
    if finding.line_end is not None and finding.line_start < finding.line_end:
        payload["start_line"] = finding.line_start
        payload["start_side"] = finding.start_side or finding.side
    return payload


async def post_review(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    result: ReviewResult,
) -> dict[str, object]:
    comments = [build_review_comment_payload(finding) for finding in result.findings]

    event = (
        "REQUEST_CHANGES"
        if any(finding.severity == "critical" for finding in result.findings)
        else "COMMENT"
    )

    payload = {
        "commit_id": head_sha,
        "body": truncate_markdown_text(result.summary, 1000),
        "event": event,
        "comments": comments,
    }
    return await gh.post_json(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", payload)
