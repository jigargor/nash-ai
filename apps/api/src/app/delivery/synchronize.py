"""Synchronize handling: skip duplicate finding keys; resolve outdated threads."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.schema import Finding
from app.delivery.comments import finding_key, nash_marker

logger = logging.getLogger(__name__)


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


async def resolve_outdated_threads(
    gh: Any,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    remaining_findings: list[Finding],
) -> int:
    """Best-effort GraphQL resolve of threads whose finding is no longer in the set.

    Returns the number of threads we attempted to resolve. Failures are logged, never raised.
    """
    remaining_ids = {finding.finding_id for finding in remaining_findings if finding.finding_id}
    remaining_ids.add(nash_marker(None))
    resolved = 0
    graphql = getattr(gh, "graphql", None)
    if not callable(graphql):
        return 0
    query = """
    query($owner:String!, $name:String!, $number:Int!) {
      repository(owner:$owner, name:$name) {
        pullRequest(number:$number) {
          reviewThreads(first: 50) {
            nodes { id isResolved comments(first: 1) { nodes { body } } }
          }
        }
      }
    }
    """
    try:
        payload = await graphql(
            query, {"owner": owner, "name": repo, "number": pr_number}
        )
    except Exception as exc:
        logger.info("synchronize GraphQL list failed: %s", exc)
        return 0
    nodes = (
        (((payload or {}).get("data") or {}).get("repository") or {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes")
        or []
    )
    mutation = """
    mutation($id:ID!) { resolveReviewThread(input:{threadId:$id}) { thread { id isResolved } } }
    """
    for node in nodes:
        if not isinstance(node, dict) or node.get("isResolved"):
            continue
        comments = ((node.get("comments") or {}).get("nodes")) or []
        body = str((comments[0] or {}).get("body") or "") if comments else ""
        fid = extract_nash_finding_id(body)
        if not fid or fid in remaining_ids:
            continue
        try:
            await graphql(mutation, {"id": node.get("id")})
            resolved += 1
        except Exception as exc:
            logger.info("synchronize resolve failed thread=%s err=%s", node.get("id"), exc)
    return resolved
