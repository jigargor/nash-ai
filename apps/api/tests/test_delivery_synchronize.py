"""resolve_outdated_threads: pagination and which threads get resolved."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.schema import Finding
from app.delivery.comments import nash_marker
from app.delivery.ids import assign_finding_ids
from app.delivery.synchronize import resolve_outdated_threads


def _finding(target: str) -> Finding:
    return Finding.model_validate(
        {
            "severity": "medium",
            "category": "correctness",
            "message": "m",
            "file_path": "src/a.ts",
            "line_start": 1,
            "target_line_content": target,
            "confidence": 90,
            "evidence": "diff_visible",
        }
    )


def _thread(thread_id: str, finding_id: str | None, *, resolved: bool = False) -> dict[str, Any]:
    body = "text" if finding_id is None else f"text\n\n{nash_marker(finding_id)}"
    return {"id": thread_id, "isResolved": resolved, "comments": {"nodes": [{"body": body}]}}


class _FakeGraphQLClient:
    def __init__(self, pages: list[dict[str, Any]], *, fail_mutation_for: str | None = None) -> None:
        self._pages = pages
        self._fail_mutation_for = fail_mutation_for
        self.list_cursors: list[str | None] = []
        self.resolved_ids: list[str] = []

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if "resolveReviewThread" in query:
            if variables["id"] == self._fail_mutation_for:
                raise RuntimeError("forbidden")
            self.resolved_ids.append(variables["id"])
            return {"data": {}}
        self.list_cursors.append(variables.get("cursor"))
        index = len(self.list_cursors) - 1
        page = self._pages[index]
        return {"data": {"repository": {"pullRequest": {"reviewThreads": page}}}}


@pytest.mark.anyio
async def test_resolve_outdated_threads_resolves_only_threads_without_current_finding() -> None:
    still_valid, fixed = assign_finding_ids([_finding("a = 1"), _finding("b = 2")])
    client = _FakeGraphQLClient(
        [
            {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    _thread("t-valid", still_valid.finding_id),
                    _thread("t-fixed", fixed.finding_id),
                    _thread("t-done", "old-id", resolved=True),
                    _thread("t-unknown", "unknown"),
                    _thread("t-human", None),
                ],
            }
        ]
    )

    resolved = await resolve_outdated_threads(
        client, owner="acme", repo="repo", pr_number=3, remaining_findings=[still_valid]
    )

    assert resolved == 1
    assert client.resolved_ids == ["t-fixed"]


@pytest.mark.anyio
async def test_resolve_outdated_threads_paginates_past_first_page() -> None:
    client = _FakeGraphQLClient(
        [
            {
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                "nodes": [_thread("t-1", "gone-1")],
            },
            {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [_thread("t-2", "gone-2")],
            },
        ]
    )

    resolved = await resolve_outdated_threads(
        client, owner="acme", repo="repo", pr_number=3, remaining_findings=[]
    )

    assert resolved == 2
    assert client.list_cursors == [None, "cursor-1"]
    assert client.resolved_ids == ["t-1", "t-2"]


@pytest.mark.anyio
async def test_resolve_outdated_threads_continues_after_mutation_failure() -> None:
    client = _FakeGraphQLClient(
        [
            {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [_thread("t-bad", "gone-1"), _thread("t-ok", "gone-2")],
            }
        ],
        fail_mutation_for="t-bad",
    )

    resolved = await resolve_outdated_threads(
        client, owner="acme", repo="repo", pr_number=3, remaining_findings=[]
    )

    assert resolved == 1
    assert client.resolved_ids == ["t-ok"]


@pytest.mark.anyio
async def test_resolve_outdated_threads_swallows_list_failure() -> None:
    class _Broken:
        async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

    resolved = await resolve_outdated_threads(
        _Broken(), owner="acme", repo="repo", pr_number=3, remaining_findings=[]
    )

    assert resolved == 0
