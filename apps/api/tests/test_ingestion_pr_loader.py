"""Ingestion: shared PR loader, control tags, Files API cross-check."""

from __future__ import annotations

from typing import Any

import pytest

from app.ingestion import (
    cross_check_diff_line_numbers,
    extract_review_control_tags,
    load_pr_context,
    should_skip_review,
)

PATH = "src/x.py"
DIFF = (
    f"diff --git a/{PATH} b/{PATH}\n"
    f"--- a/{PATH}\n"
    f"+++ b/{PATH}\n"
    "@@ -1,2 +1,3 @@\n"
    " import os\n"
    "+import sys\n"
    " print(os.name)\n"
)
PATCH = "@@ -1,2 +1,3 @@\n import os\n+import sys\n print(os.name)"


def test_control_tags_force_beats_skip() -> None:
    assert extract_review_control_tags("[skip-nash-review]") == {"skip": True, "force": False}
    assert should_skip_review("chore", "[skip-nash-review]") is True
    assert should_skip_review("chore [SKIP-NASH-REVIEW]", "[force-nash-review]") is False
    assert should_skip_review("plain", None) is False


def test_cross_check_agrees_when_files_api_matches_unidiff() -> None:
    assert cross_check_diff_line_numbers(DIFF, [{"filename": PATH, "patch": PATCH}]) == []


def test_cross_check_flags_disagreement_and_missing_files() -> None:
    shifted = "@@ -1,2 +1,3 @@\n import os\n print(os.name)\n+import sys"
    warnings = cross_check_diff_line_numbers(
        DIFF, [{"filename": PATH, "patch": shifted}, {"filename": "other.py", "patch": "@@ -1 +1 @@\n+x"}]
    )
    assert any(w.startswith(f"added_lines_mismatch:{PATH}") for w in warnings)
    assert "files_api_only:other.py" in warnings


class _FakeReader:
    def __init__(self, *, with_files_api: bool) -> None:
        self.with_files_api = with_files_api
        if with_files_api:
            self.get_pull_request_files = self._files  # type: ignore[method-assign]

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        return {
            "title": "feat: add sys import",
            "body": "why not",
            "draft": False,
            "head": {"sha": "h" * 40},
            "base": {"sha": "b" * 40},
        }

    async def get_pull_request_diff(self, owner: str, repo: str, pr_number: int) -> str:
        return DIFF

    async def get_pull_request_commits(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        return [{"sha": "c" * 40, "commit": {"message": "add sys import\n\nbody"}}]

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        return "import os\nimport sys\nprint(os.name)\n"

    async def _files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        return [{"filename": PATH, "patch": PATCH}]


@pytest.mark.anyio
async def test_load_pr_context_populates_metadata_commentable_lines_and_files() -> None:
    pr = await load_pr_context(_FakeReader(with_files_api=True), owner="acme", repo="demo", pr_number=3)

    assert pr.title == "feat: add sys import"
    assert pr.base_sha == "b" * 40
    assert pr.commits[0].message.startswith("add sys import")
    assert (PATH, 2) in pr.commentable_lines
    assert pr.files_at_head[PATH].startswith("import os")
    assert pr.diff_cross_check_warnings == []


@pytest.mark.anyio
async def test_load_pr_context_without_files_api_skips_cross_check() -> None:
    pr = await load_pr_context(_FakeReader(with_files_api=False), owner="acme", repo="demo", pr_number=3)
    assert pr.diff_cross_check_warnings == []
    assert pr.head_sha == "h" * 40
