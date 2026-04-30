import pytest

from app.agent.consistency_probe import run_consistency_probe
from app.agent.consistency_probe_schema import ProbeCandidate
from app.agent.review_config import ConsistencyProbeConfig, ReviewConfig
from app.agent.schema import EditedReview, ReviewResult


def _review_result() -> ReviewResult:
    return ReviewResult.model_validate(
        {
            "summary": "draft",
            "findings": [
                {
                    "severity": "high",
                    "category": "security",
                    "message": "Unsanitized output in template rendering.",
                    "file_path": "src/app.py",
                    "line_start": 7,
                    "line_end": 7,
                    "target_line_content": "render(user_input)",
                    "suggestion": None,
                    "confidence": 90,
                    "evidence": "diff_visible",
                }
            ],
        }
    )


def _edited_review() -> EditedReview:
    return EditedReview.model_validate({"summary": "edited", "findings": [], "decisions": []})


@pytest.mark.anyio
async def test_probe_returns_skipped_when_disabled() -> None:
    review_config = ReviewConfig(consistency_probe=ConsistencyProbeConfig(enabled=False))
    result = await run_consistency_probe(
        draft_result=_review_result(),
        edited_result=_edited_review(),
        unresolved_candidates=[],
        deterministic_reason="missing_from_final",
        review_config=review_config,
        context={"review_id": 1, "installation_id": 1},
    )
    assert result.skipped_reason == "probe_disabled"


@pytest.mark.anyio
async def test_probe_returns_skipped_when_no_candidates() -> None:
    review_config = ReviewConfig(consistency_probe=ConsistencyProbeConfig(enabled=True))
    result = await run_consistency_probe(
        draft_result=_review_result(),
        edited_result=_edited_review(),
        unresolved_candidates=[],
        deterministic_reason="missing_from_final",
        review_config=review_config,
        context={"review_id": 1, "installation_id": 1},
    )
    assert result.skipped_reason == "no_unresolved_candidates"


@pytest.mark.anyio
async def test_probe_returns_budget_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_budget(**_: object) -> bool:
        return False

    monkeypatch.setattr("app.agent.consistency_probe._consume_probe_budget", _no_budget)
    review_config = ReviewConfig(consistency_probe=ConsistencyProbeConfig(enabled=True))
    result = await run_consistency_probe(
        draft_result=_review_result(),
        edited_result=_edited_review(),
        unresolved_candidates=[
            ProbeCandidate(
                candidate_id="abc123",
                title="Unsanitized output in template rendering.",
                severity="high",
                category="security",
                path="src/app.py",
                line_start=7,
                line_end=7,
                evidence="diff_visible",
                evidence_fact_id=None,
                summary_hash="abc123",
            )
        ],
        deterministic_reason="missing_from_final",
        review_config=review_config,
        context={"review_id": 1, "installation_id": 1},
    )
    assert result.skipped_reason == "budget_cap_reached"

