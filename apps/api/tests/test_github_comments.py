import pytest

from app.agent.schema import Finding, ReviewResult
from app.github.comments import build_review_comment_payload, format_finding, post_review


def test_build_review_comment_payload_adds_start_line_for_multiline() -> None:
    finding = Finding.model_validate(
        {
            "severity": "medium",
            "category": "correctness",
            "message": "Multi-line issue.",
            "file_path": "x.ts",
            "line_start": 2,
            "line_end": 5,
            "target_line_content": "first",
            "suggestion": None,
            "confidence": 90,
            "evidence": "diff_visible",
        }
    )
    payload = build_review_comment_payload(finding)
    assert payload["line"] == 5
    assert payload["start_line"] == 2
    assert payload["start_side"] == "RIGHT"


def test_build_review_comment_payload_omits_start_line_when_single_line() -> None:
    finding = Finding.model_validate(
        {
            "severity": "low",
            "category": "style",
            "message": "Nit.",
            "file_path": "x.ts",
            "line_start": 1,
            "line_end": None,
            "target_line_content": "x",
            "suggestion": None,
            "confidence": 90,
            "evidence": "diff_visible",
        }
    )
    payload = build_review_comment_payload(finding)
    assert payload["line"] == 1
    assert "start_line" not in payload


def test_format_finding_sanitizes_message_tail() -> None:
    finding = Finding.model_validate(
        {
            "severity": "medium",
            "category": "correctness",
            "message": "Details\n-",
            "file_path": "a.py",
            "line_start": 1,
            "target_line_content": "x = 1",
            "suggestion": None,
            "confidence": 90,
            "evidence": "diff_visible",
        }
    )
    body = format_finding(finding)
    assert "Details\n-" not in body
    assert "Details" in body


class _FakeGitHubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((path, payload))
        return {"id": 123}


@pytest.mark.anyio
async def test_post_review_skips_non_actionable_empty_chunk_summary() -> None:
    gh = _FakeGitHubClient()
    result = ReviewResult(
        findings=[],
        summary="Chunked review coverage: 57/57 review-surface files; 5 files skipped by pre-pass. No chunk summaries were available for synthesis.",
    )

    response = await post_review(gh, "acme", "repo", 7, "a" * 40, result)

    assert response == {}
    assert gh.calls == []


@pytest.mark.anyio
async def test_post_review_posts_when_findings_present() -> None:
    gh = _FakeGitHubClient()
    result = ReviewResult(
        findings=[
            Finding.model_validate(
                {
                    "severity": "medium",
                    "category": "correctness",
                    "message": "Potential issue.",
                    "file_path": "x.ts",
                    "line_start": 1,
                    "target_line_content": "x",
                    "confidence": 90,
                    "evidence": "diff_visible",
                }
            )
        ],
        summary="Actionable review.",
    )

    response = await post_review(gh, "acme", "repo", 8, "b" * 40, result)

    assert response == {"id": 123}
    assert len(gh.calls) == 1
