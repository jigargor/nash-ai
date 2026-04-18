from app.agent.schema import Finding, ReviewResult
from app.github.client import GitHubClient


def format_finding(finding: Finding) -> str:
    body = (
        f"**{finding.severity} · {finding.category}** · confidence {finding.confidence:.0%}\n\n"
        f"{finding.message}"
    )
    if finding.suggestion:
        body = f"{body}\n\n```suggestion\n{finding.suggestion}\n```"
    return body


async def post_review(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    result: ReviewResult,
) -> None:
    comments = [
        {
            "path": finding.file_path,
            "line": finding.line_end or finding.line_start,
            "side": "RIGHT",
            "body": format_finding(finding),
        }
        for finding in result.findings
    ]

    event = "REQUEST_CHANGES" if any(finding.severity == "critical" for finding in result.findings) else "COMMENT"

    payload = {
        "commit_id": head_sha,
        "body": result.summary,
        "event": event,
        "comments": comments,
    }
    await gh.post_json(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", payload)
