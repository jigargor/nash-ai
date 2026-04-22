from app.agent.schema import Finding
from app.agent.vendor_detect import auto_tag_vendor_claims, looks_like_vendor_claim


def _finding(message: str, **overrides: object) -> Finding:
    payload: dict[str, object] = {
        "severity": "medium",
        "category": "correctness",
        "message": message,
        "file_path": "a.py",
        "line_start": 1,
        "line_end": 1,
        "target_line_content": "x = 1",
        "confidence": 70,
        "evidence": "diff_visible",
    }
    payload.update(overrides)
    return Finding.model_validate(payload)


def test_looks_like_vendor_claim_detects_vercel_keyword() -> None:
    assert looks_like_vendor_claim("x-vercel-forwarded-for handling may be incorrect")


def test_auto_tag_vendor_claims_marks_detected_vendor_message() -> None:
    finding = _finding("This discusses Supabase generated types behavior.")
    accepted, rejected = auto_tag_vendor_claims([finding])
    assert not rejected
    assert accepted[0].is_vendor_claim is True


def test_auto_tag_vendor_claims_rejects_now_invalid_finding() -> None:
    finding = _finding(
        "x-vercel-forwarded-for parsing is definitely vulnerable.",
        severity="critical",
        evidence="verified_fact",
        evidence_fact_id="vercel_forwarded_for",
    )
    accepted, rejected = auto_tag_vendor_claims([finding])
    assert not accepted
    assert len(rejected) == 1
    assert "auto_tagged_vendor_claim_invalid" in rejected[0][1]
