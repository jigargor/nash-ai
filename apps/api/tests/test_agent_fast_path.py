from app.agent.diff_parser import FileInDiff, NumberedLine
from app.agent.fast_path import (
    FastPathDecision,
    build_fast_path_prompt,
    fast_path_metadata,
    is_high_risk_path,
    normalize_fast_path_decision,
)
from app.agent.review_config import FastPathConfig
from app.agent.chunking import classify_diff_files


def _file(path: str, *, added_lines: int = 2) -> FileInDiff:
    return FileInDiff(
        path=path,
        language="Markdown",
        is_new=False,
        is_deleted=False,
        numbered_lines=[
            NumberedLine(
                new_line_no=index + 1, old_line_no=index + 1, kind="add", content=f"line_{index}"
            )
            for index in range(added_lines)
        ],
        context_window=[],
    )


def test_build_fast_path_prompt_includes_manifest_classes_and_diff_excerpt() -> None:
    files = [_file("docs/README.md"), _file("src/generated/client.ts")]
    classified = classify_diff_files(files, generated_paths=["src/generated/**"], vendor_paths=[])

    prompt = build_fast_path_prompt(
        classified,
        diff_text="diff --git a/docs/README.md b/docs/README.md\n+hello",
        pr={"title": "Docs update", "body": "Refresh docs"},
        commits=[{"commit": {"message": "docs: refresh"}}],
        max_diff_excerpt_tokens=100,
    )

    assert "docs/README.md" in prompt
    assert '"class": "docs_only"' in prompt
    assert "src/generated/client.ts" in prompt
    assert '"class": "generated"' in prompt
    assert "extension_histogram" in prompt
    assert "+hello" in prompt


def test_normalize_invalid_decision_escalates_to_full_review() -> None:
    decision = normalize_fast_path_decision({"decision": "skip_review"}, FastPathConfig(), [])

    assert decision.decision == "full_review"
    assert (
        "invalid decision schema" in decision.reason
        or "omitted confidence" in decision.reason
    )


def test_normalize_missing_confidence_escalates_to_full_review() -> None:
    decision = normalize_fast_path_decision(
        {
            "decision": "skip_review",
            "risk_labels": ["docs_only"],
            "reason": "safe",
            "review_surface": ["docs/README.md"],
            "requires_full_context": False,
        },
        FastPathConfig(),
        [],
    )

    assert decision.decision == "full_review"
    assert "missing_confidence" in decision.risk_labels


def test_normalize_recovers_confidence_from_alias_key() -> None:
    decision = normalize_fast_path_decision(
        {
            "decision": "light_review",
            "risk_labels": ["config_only"],
            "reason": "Small config-only change.",
            "confidence_score": 88,
            "review_surface": ["apps/web/next.config.ts"],
            "requires_full_context": False,
        },
        FastPathConfig(light_review_min_confidence=80),
        classify_diff_files([_file("apps/web/next.config.ts")], generated_paths=[], vendor_paths=[]),
    )

    assert decision.decision == "light_review"
    assert decision.confidence == 88
    assert "confidence_recovered" in decision.risk_labels


def test_normalize_recovers_confidence_from_low_risk_heuristic() -> None:
    decision = normalize_fast_path_decision(
        {
            "decision": "skip_review",
            "risk_labels": ["docs_only"],
            "reason": "Only docs changed.",
            "review_surface": ["docs/README.md"],
            "requires_full_context": False,
        },
        FastPathConfig(skip_min_confidence=90),
        classify_diff_files([_file("docs/README.md", added_lines=3)], generated_paths=[], vendor_paths=[]),
    )

    assert decision.decision == "skip_review"
    assert decision.confidence is not None
    assert decision.confidence >= 90
    assert "confidence_recovered" in decision.risk_labels


def test_low_confidence_skip_escalates_to_full_review() -> None:
    raw = FastPathDecision(
        decision="skip_review",
        risk_labels=["docs_only"],
        reason="Only docs changed.",
        confidence=75,
        review_surface=["docs/README.md"],
        requires_full_context=False,
    )

    decision = normalize_fast_path_decision(
        raw.model_dump(), FastPathConfig(skip_min_confidence=90), []
    )

    assert decision.decision == "full_review"
    assert "low_confidence" in decision.risk_labels


def test_high_risk_path_prevents_skip_review() -> None:
    classified = classify_diff_files(
        [_file("apps/api/src/auth/session.py")], generated_paths=[], vendor_paths=[]
    )
    raw = FastPathDecision(
        decision="skip_review",
        risk_labels=["small_change"],
        reason="Looks tiny.",
        confidence=99,
        review_surface=["apps/api/src/auth/session.py"],
        requires_full_context=False,
    )

    decision = normalize_fast_path_decision(raw.model_dump(), FastPathConfig(), classified)

    assert decision.decision == "full_review"
    assert "high_risk_path" in decision.risk_labels
    assert decision.requires_full_context is True


def test_high_risk_path_detection_covers_security_sensitive_surfaces() -> None:
    assert is_high_risk_path("apps/api/alembic/versions/add_rls_policy.py") is True
    assert is_high_risk_path(".github/workflows/api-db-security.yml") is True
    assert is_high_risk_path("docs/README.md") is False


def test_fast_path_metadata_separates_surface_paths_and_count() -> None:
    classified = classify_diff_files(
        [_file("apps/web/next.config.ts", added_lines=5)],
        generated_paths=[],
        vendor_paths=[],
    )
    decision = FastPathDecision(
        decision="full_review",
        risk_labels=["missing_confidence"],
        reason="Escalated for safety.",
        confidence=None,
        review_surface=["apps/web/next.config.ts"],
        requires_full_context=True,
    )

    metadata = fast_path_metadata(
        decision,
        classified=classified,
        diff_tokens=123,
        fallback_reason="missing_confidence",
    )

    assert metadata["review_surface_paths"] == ["apps/web/next.config.ts"]
    assert metadata["review_surface_count"] == 1
    assert metadata["review_surface"] == ["apps/web/next.config.ts"]
    assert sum(int(value) for value in metadata["file_classes"].values()) == 1


def test_fast_path_metadata_marks_recovered_confidence_source() -> None:
    decision = FastPathDecision(
        decision="full_review",
        risk_labels=["missing_confidence", "confidence_recovered"],
        reason="Escalated for safety.",
        confidence=65,
        review_surface=["apps/web/next.config.ts"],
        requires_full_context=True,
    )
    metadata = fast_path_metadata(
        decision,
        classified=classify_diff_files(
            [_file("apps/web/next.config.ts", added_lines=5)], generated_paths=[], vendor_paths=[]
        ),
        diff_tokens=123,
        fallback_reason="missing_confidence",
    )
    assert metadata["confidence_source"] == "recovered"
