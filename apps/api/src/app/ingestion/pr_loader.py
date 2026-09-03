"""PR context loader shared by worker and eval harness."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agent.diff_parser import parse_diff, right_side_diff_line_set
from app.agent.schema import CommitSummary, PRContext
from app.github.utils import safe_fetch_file

logger = logging.getLogger(__name__)

SKIP_TAG = "[skip-nash-review]"
FORCE_TAG = "[force-nash-review]"


def extract_review_control_tags(text: str) -> dict[str, bool]:
    lowered = (text or "").lower()
    return {
        "skip": SKIP_TAG.lower() in lowered,
        "force": FORCE_TAG.lower() in lowered,
    }


def should_skip_review(title: str | None, body: str | None) -> bool:
    """``[skip-nash-review]`` wins unless ``[force-nash-review]`` is also present."""
    tags = extract_review_control_tags(f"{title or ''}\n{body or ''}")
    return tags["skip"] and not tags["force"]


async def load_pr_context(
    gh: Any,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str | None = None,
    installation_id: int | None = None,
    review_id: int | None = None,
    prefetch_files: bool = True,
    max_prefetch_files: int = 40,
    cross_check_files_api: bool = True,
) -> PRContext:
    """Fetch PR metadata + unified diff (+ optional HEAD file contents).

    When the reader exposes ``get_pull_request_files`` the unidiff line numbers are
    cross-checked against the Files API patches; disagreements are recorded on the
    context (non-fatal) so anchoring failures can be traced to ingestion.
    """
    pr = await gh.get_pull_request(owner, repo, pr_number)
    diff_text = await gh.get_pull_request_diff(owner, repo, pr_number)
    commits_raw = await gh.get_pull_request_commits(owner, repo, pr_number)
    resolved_head = head_sha or str((pr.get("head") or {}).get("sha") or "")
    base_sha = str((pr.get("base") or {}).get("sha") or "") or None
    title = str(pr.get("title") or "")
    body = str(pr.get("body") or "")
    commits = [
        CommitSummary(
            sha=str(item.get("sha") or "") or None,
            message=str(((item.get("commit") or {}).get("message")) or ""),
        )
        for item in commits_raw
        if isinstance(item, dict)
    ]
    files_in_diff = parse_diff(diff_text)
    commentable = sorted(right_side_diff_line_set(files_in_diff))
    files_at_head: dict[str, str] = {}
    if prefetch_files and resolved_head:
        for file in files_in_diff[:max_prefetch_files]:
            if file.is_deleted:
                continue
            content = await safe_fetch_file(gh, owner, repo, file.path, resolved_head)
            if content is not None:
                files_at_head[file.path] = content

    warnings: list[str] = []
    files_api_getter = getattr(gh, "get_pull_request_files", None)
    if cross_check_files_api and callable(files_api_getter):
        try:
            files_api_entries = await files_api_getter(owner, repo, pr_number)
            if isinstance(files_api_entries, list):
                warnings = cross_check_diff_line_numbers(diff_text, files_api_entries)
        except Exception as exc:  # cross-check is a probe; never block ingestion
            logger.info("Files API cross-check skipped: %s", exc)
            warnings = [f"files_api_unavailable:{exc.__class__.__name__}"]

    return PRContext(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        head_sha=resolved_head,
        base_sha=base_sha,
        title=title,
        body=body,
        draft=bool(pr.get("draft", False)),
        commits=commits,
        diff_text=diff_text,
        files_at_head=files_at_head,
        commentable_lines=commentable,
        installation_id=installation_id,
        review_id=review_id,
        diff_cross_check_warnings=warnings,
    )


_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _added_line_numbers_from_patch(patch: str) -> set[int]:
    """Right-side line numbers of added lines in a GitHub Files API ``patch``."""
    added: set[int] = set()
    new_line = 0
    for raw in patch.split("\n"):
        header = _HUNK_HEADER.match(raw)
        if header:
            new_line = int(header.group(1))
            continue
        if raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            added.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            new_line += 1
    return added


def cross_check_diff_line_numbers(
    diff_text: str,
    files_api_entries: list[dict[str, Any]],
) -> list[str]:
    """Return warnings when unidiff right-side line sets disagree with Files API patches.

    Exact set comparison of added-line numbers per file; ``files_api_only`` flags files
    present in the Files API but missing from the parsed unidiff (and vice versa).
    """
    warnings: list[str] = []
    parsed = {f.path: f for f in parse_diff(diff_text)}
    seen: set[str] = set()
    for entry in files_api_entries:
        path = str(entry.get("filename") or "")
        patch = entry.get("patch")
        if not path:
            continue
        seen.add(path)
        file = parsed.get(path)
        if file is None:
            warnings.append(f"files_api_only:{path}")
            continue
        if not isinstance(patch, str):
            continue  # binary / too large: GitHub omits the patch
        api_added = _added_line_numbers_from_patch(patch)
        unidiff_added = {
            int(line.new_line_no)
            for line in file.numbered_lines
            if line.kind == "add" and line.new_line_no is not None
        }
        if api_added != unidiff_added:
            only_api = sorted(api_added - unidiff_added)[:5]
            only_unidiff = sorted(unidiff_added - api_added)[:5]
            warnings.append(
                f"added_lines_mismatch:{path}:files_api_only={only_api}:unidiff_only={only_unidiff}"
            )
    for path in parsed:
        if path not in seen and files_api_entries:
            warnings.append(f"unidiff_only:{path}")
    return warnings
