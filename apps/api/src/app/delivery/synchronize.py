"""Synchronize handling: skip duplicate finding keys; resolve outdated threads."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.schema import Finding
from app.delivery.comments import finding_key

logger = logging.getLogger(__name__)

_THREADS_PAGE_SIZE = 100
_MAX_THREAD_PAGES = 10
_UNKNOWN_FINDING_ID = "unknown"

_LIST_THREADS_QUERY = """
query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first: %d, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id isResolved comments(first: 1) { nodes { body } } }
      }
    }
  }
}
""" % _THREADS_PAGE_SIZE

_RESOLVE_THREAD_MUTATION = """
mutation($id:ID!) { resolveReviewThread(input:{threadId:$id}) { thread { id isResolved } } }
"""


def extract_nash_finding_id(body: str) -> str | None:
    marker_prefix = "<!-- nash:f:"
    start = body.find(marker_prefix)
    if start < 0:
        return None
    rest = body[start + len(marker_prefix) :]
    end = rest.find(" -->")
    if end < 0:
        return None
    fid = rest[:end].strip()
    return fid or None


def filter_new_findings(
    findings: list[Finding],
    existing_comments: list[dict[str, Any]],
) -> list[Finding]:
    """Drop findings already posted on this PR (same path+line+category or marker id)."""
    existing_keys: set[tuple[str, int, str]] = set()
    existing_ids: set[str] = set()
    for comment in existing_comments:
        path = str(comment.get("path") or "")
        line = comment.get("line") or comment.get("original_line") or 0
        body = str(comment.get("body") or "")
        fid = extract_nash_finding_id(body)
        if fid:
            existing_ids.add(fid)
        if path and isinstance(line, int):
            category = ""
            existing_keys.add((path, line, category))
    kept: list[Finding] = []
    for finding in findings:
        if finding.finding_id and finding.finding_id in existing_ids:
            continue
        key = finding_key(finding)
        if any(k[0] == key[0] and k[1] == key[1] for k in existing_keys):
            # Same file+line already commented; skip unless marker ids differ and none match.
            if not finding.finding_id:
                continue
        kept.append(finding)
    return kept


async def _list_review_threads(graphql: Any, *, owner: str, repo: str, pr_number: int) -> list[Any]:
    """Collect review threads across pages (bounded). Raises on GraphQL failure."""
    threads: list[Any] = []
    cursor: str | None = None
    for _ in range(_MAX_THREAD_PAGES):
        payload = await graphql(
            _LIST_THREADS_QUERY,
            {"owner": owner, "name": repo, "number": pr_number, "cursor": cursor},
        )
        repository = ((payload or {}).get("data") or {}).get("repository") or {}
        review_threads = (repository.get("pullRequest") or {}).get("reviewThreads") or {}
        nodes = review_threads.get("nodes") or []
        threads.extend(nodes)
        page_info = review_threads.get("pageInfo") or {}
        cursor = page_info.get("endCursor")
        if not page_info.get("hasNextPage") or not cursor:
            break
    else:
        logger.info(
            "synchronize: stopped listing review threads after %s pages", _MAX_THREAD_PAGES
        )
    return threads


async def resolve_outdated_threads(
    gh: Any,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    remaining_findings: list[Finding],
) -> int:
    """Best-effort GraphQL resolve of threads whose finding is no longer in the set.

    ``remaining_findings`` must be the full current finding set (including findings whose
    comments already exist), otherwise still-valid threads would be resolved.

    Returns the number of threads resolved. Failures are logged, never raised.
    """
    remaining_ids = {finding.finding_id for finding in remaining_findings if finding.finding_id}
    # Never auto-resolve threads whose marker carries no real finding id.
    remaining_ids.add(_UNKNOWN_FINDING_ID)
    graphql = getattr(gh, "graphql", None)
    if not callable(graphql):
        return 0
    try:
        nodes = await _list_review_threads(graphql, owner=owner, repo=repo, pr_number=pr_number)
    except Exception as exc:
        logger.info("synchronize GraphQL list failed: %s", exc)
        return 0
    resolved = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("isResolved"):
            continue
        comments = ((node.get("comments") or {}).get("nodes")) or []
        body = str((comments[0] or {}).get("body") or "") if comments else ""
        fid = extract_nash_finding_id(body)
        if not fid or fid in remaining_ids:
            continue
        try:
            await graphql(_RESOLVE_THREAD_MUTATION, {"id": node.get("id")})
            resolved += 1
        except Exception as exc:
            logger.info("synchronize resolve failed thread=%s err=%s", node.get("id"), exc)
    return resolved
