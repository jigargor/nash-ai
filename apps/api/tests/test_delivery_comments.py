"""Delivery renderer: human-style bodies, hidden markers, batching, 422 fallback."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.schema import Finding, ReviewResult
from app.delivery import (
    extract_nash_finding_id,
    filter_new_findings,
    format_finding_human,
    post_review_batched,
    review_event_for,
)


def _finding(line: int = 1, **overrides: Any) -> Finding:
    payload: dict[str, Any] = {
        "severity": "medium",
        "category": "correctness",
        "message": "Null check happens after dereference.",
        "file_path": "src/a.ts",
        "line_start": line,
        "target_line_content": "x",
        "confidence": 90,
        "evidence": "diff_visible",
    }
    payload.update(overrides)
    return Finding.model_validate(payload)


def test_format_finding_human_has_no_confidence_or_category_prefix() -> None:
    body = format_finding_human(_finding(finding_id="f0-abc"))

    assert body.startswith("**medium** — Null check happens after dereference.")
    assert "confidence" not in body.lower()
    assert "correctness" not in body
    assert "<!-- nash:f:f0-abc -->" in body


def test_extract_nash_finding_id_roundtrip() -> None:
    body = format_finding_human(_finding(finding_id="f3-deadbeef"))
    assert extract_nash_finding_id(body) == "f3-deadbeef"
    assert extract_nash_finding_id("no marker here") is None


def test_review_event_policy() -> None:
    critical = ReviewResult(findings=[_finding(severity="high")], summary="s")
    assert review_event_for(critical, "critical_only") == "COMMENT"
    assert review_event_for(critical, "high_or_above") == "REQUEST_CHANGES"
    assert review_event_for(critical, "never") == "COMMENT"
    assert review_event_for(critical, "always") == "REQUEST_CHANGES"


def test_filter_new_findings_skips_already_posted_marker() -> None:
    posted = _finding(line=3, finding_id="f0-1111")
    fresh = _finding(line=9, finding_id="f1-2222")
    existing = [{"path": "src/a.ts", "line": 3, "body": format_finding_human(posted)}]

    kept = filter_new_findings([posted, fresh], existing)

    assert [f.finding_id for f in kept] == ["f1-2222"]


class _FlakyGitHub:
    """First batch POST fails with a 422-like error; single-comment posts succeed except line 2."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        comments = payload["comments"]
        if len(comments) > 1:
            raise RuntimeError("422 Unprocessable Entity: line must be part of the diff")
        if comments[0]["line"] == 2:
            raise RuntimeError("422 Unprocessable Entity: pull_request_review_thread.line")
        return {"id": 500 + comments[0]["line"], "comments": [{"id": 900 + comments[0]["line"]}]}


@pytest.mark.anyio
async def test_batch_failure_falls_back_per_comment_and_reports_rejected() -> None:
    gh = _FlakyGitHub()
    result = ReviewResult(findings=[_finding(1), _finding(2), _finding(3)], summary="Three.")

    response = await post_review_batched(gh, "acme", "demo", 1, "a" * 40, result)  # type: ignore[arg-type]

    assert len(gh.calls) == 4  # 1 failed batch + 3 single posts
    assert [item["line_start"] for item in response["rejected"]] == [2]  # type: ignore[index]
    assert response["comment_ids"] == [901, None, 903]
    assert response["event"] == "COMMENT"


class _RecordingGitHub:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        return {"id": 1, "comments": [{"id": 10 + i} for i, _ in enumerate(payload["comments"])]}


@pytest.mark.anyio
async def test_large_reviews_are_batched() -> None:
    gh = _RecordingGitHub()
    findings = [_finding(i + 1) for i in range(85)]
    result = ReviewResult(findings=findings, summary="Many.")

    response = await post_review_batched(gh, "acme", "demo", 1, "a" * 40, result)  # type: ignore[arg-type]

    assert [len(p["comments"]) for p in gh.payloads] == [80, 5]
    assert gh.payloads[0]["body"] == "Many."
    assert gh.payloads[1]["body"] == ""  # continuation batch carries no summary
    assert len(response["comment_ids"]) == 85  # type: ignore[arg-type]
