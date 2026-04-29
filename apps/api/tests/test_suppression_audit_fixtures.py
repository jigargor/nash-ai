import json
from pathlib import Path

import pytest

from app.agent.schema import EditedReview, ReviewResult
from app.agent.suppression_audit import run_suppression_audit

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "suppression"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "readme-instruction-suppression.json",
        "dedupe-weakening.json",
        "generated-file-overreach.json",
    ],
)
def test_suppression_audit_fixtures_detect_expected_reason(fixture_name: str) -> None:
    payload = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
    draft = ReviewResult.model_validate(payload["draft_result"])
    edited = EditedReview.model_validate(payload["edited_result"])

    audit = run_suppression_audit(draft, edited, high_critical_only=True)
    assert audit.suppressed, f"{fixture_name} should yield at least one suppression"
    assert audit.suppressed[0].reason_code == payload["expected_reason_code"]
    assert audit.suppressed[0].unresolved is payload["expected_unresolved"]

