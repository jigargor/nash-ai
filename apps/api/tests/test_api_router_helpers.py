"""Unit tests for pure functions in app.api.router.

These tests have no DB dependencies and no async requirements — they run fast
and serve as a stable baseline that is immune to Python-version coverage
instrumentation differences.

Endpoint integration tests live in test_api_router.py.
"""
from __future__ import annotations

from types import SimpleNamespace

import yaml

from app.agent.review_config import ReviewConfig
from app.api import router as api_router


# ---------------------------------------------------------------------------
# _findings_count_from_review_row
# ---------------------------------------------------------------------------


def test_findings_count_returns_count() -> None:
    review = SimpleNamespace(findings={"findings": [{"severity": "high"}, {"severity": "low"}]})
    assert api_router._findings_count_from_review_row(review) == 2  # type: ignore[attr-defined]


def test_findings_count_none_findings() -> None:
    assert api_router._findings_count_from_review_row(SimpleNamespace(findings=None)) == 0  # type: ignore[attr-defined]


def test_findings_count_non_dict() -> None:
    assert api_router._findings_count_from_review_row(SimpleNamespace(findings="bad")) == 0  # type: ignore[attr-defined]


def test_findings_count_non_list_value() -> None:
    review = SimpleNamespace(findings={"findings": "not-a-list"})
    assert api_router._findings_count_from_review_row(review) == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _as_int_or_none
# ---------------------------------------------------------------------------


def test_as_int_or_none_int() -> None:
    assert api_router._as_int_or_none(42) == 42  # type: ignore[attr-defined]


def test_as_int_or_none_whole_float() -> None:
    assert api_router._as_int_or_none(3.0) == 3  # type: ignore[attr-defined]


def test_as_int_or_none_fractional_float() -> None:
    assert api_router._as_int_or_none(3.5) is None  # type: ignore[attr-defined]


def test_as_int_or_none_bool() -> None:
    assert api_router._as_int_or_none(True) is None  # type: ignore[attr-defined]


def test_as_int_or_none_string() -> None:
    assert api_router._as_int_or_none("42") is None  # type: ignore[attr-defined]


def test_as_int_or_none_none() -> None:
    assert api_router._as_int_or_none(None) is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _diff_stats_from_debug_artifacts
# ---------------------------------------------------------------------------


def test_diff_stats_returns_values() -> None:
    review = SimpleNamespace(debug_artifacts={
        "fast_path_decision": {"changed_file_count": 5, "changed_line_count": 120}
    })
    files, lines = api_router._diff_stats_from_debug_artifacts(review)  # type: ignore[attr-defined]
    assert files == 5
    assert lines == 120


def test_diff_stats_none_artifacts() -> None:
    files, lines = api_router._diff_stats_from_debug_artifacts(SimpleNamespace(debug_artifacts=None))  # type: ignore[attr-defined]
    assert files is None and lines is None


def test_diff_stats_empty_artifacts() -> None:
    files, lines = api_router._diff_stats_from_debug_artifacts(SimpleNamespace(debug_artifacts={}))  # type: ignore[attr-defined]
    assert files is None and lines is None


def test_diff_stats_non_dict_fast_path() -> None:
    review = SimpleNamespace(debug_artifacts={"fast_path_decision": "bad"})
    files, lines = api_router._diff_stats_from_debug_artifacts(review)  # type: ignore[attr-defined]
    assert files is None and lines is None


# ---------------------------------------------------------------------------
# _validate_repo_segment
# ---------------------------------------------------------------------------


def test_validate_repo_segment_valid() -> None:
    result = api_router._validate_repo_segment("acme-org", "owner")  # type: ignore[attr-defined]
    assert result == "acme-org"


def test_validate_repo_segment_invalid_slash() -> None:
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException) as exc_info:
        api_router._validate_repo_segment("bad/segment", "owner")  # type: ignore[attr-defined]
    assert exc_info.value.status_code == 400


def test_validate_repo_segment_empty() -> None:
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException):
        api_router._validate_repo_segment("  ", "owner")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _extract_yaml_payload
# ---------------------------------------------------------------------------


def test_extract_yaml_strips_fenced_block() -> None:
    raw = "```yaml\nkey: value\n```"
    assert api_router._extract_yaml_payload(raw) == "key: value"  # type: ignore[attr-defined]


def test_extract_yaml_strips_yml_fence() -> None:
    raw = "```yml\nfoo: bar\n```"
    assert api_router._extract_yaml_payload(raw) == "foo: bar"  # type: ignore[attr-defined]


def test_extract_yaml_plain_text() -> None:
    raw = "key: value"
    assert api_router._extract_yaml_payload(raw) == "key: value"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _normalize_generated_config
# ---------------------------------------------------------------------------


def test_normalize_generated_config_defaults() -> None:
    config = api_router._normalize_generated_config({})  # type: ignore[attr-defined]
    assert isinstance(config, ReviewConfig)
    assert config.prompt_additions is None


def test_normalize_generated_config_with_fields() -> None:
    config = api_router._normalize_generated_config({  # type: ignore[attr-defined]
        "confidence_threshold": 90,
        "severity_threshold": "high",
        "categories": ["security", "correctness"],
    })
    assert config.confidence_threshold == 90
    assert config.severity_threshold == "high"
    assert "security" in config.categories


def test_normalize_generated_config_empty_prompt_additions() -> None:
    # Empty string prompt_additions should become None
    config = api_router._normalize_generated_config({"prompt_additions": ""})  # type: ignore[attr-defined]
    assert config.prompt_additions is None


def test_normalize_generated_config_whitespace_prompt_additions() -> None:
    config = api_router._normalize_generated_config({"prompt_additions": "   "})  # type: ignore[attr-defined]
    assert config.prompt_additions is None


def test_normalize_generated_config_with_prompt_additions() -> None:
    config = api_router._normalize_generated_config({"prompt_additions": "  focus on SQL  "})  # type: ignore[attr-defined]
    assert config.prompt_additions == "focus on SQL"


def test_normalize_generated_config_non_string_prompt_additions() -> None:
    # Non-string prompt_additions should become None (not isinstance str)
    config = api_router._normalize_generated_config({"prompt_additions": 42})  # type: ignore[attr-defined]
    assert config.prompt_additions is None


# ---------------------------------------------------------------------------
# _serialize_review_config_yaml
# ---------------------------------------------------------------------------


def test_serialize_review_config_yaml_roundtrips() -> None:
    config = ReviewConfig()
    text = api_router._serialize_review_config_yaml(config)  # type: ignore[attr-defined]
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, dict)
    assert "confidence_threshold" in parsed
    assert "severity_threshold" in parsed


def test_serialize_review_config_yaml_decimal_as_float() -> None:
    config = ReviewConfig()
    text = api_router._serialize_review_config_yaml(config)  # type: ignore[attr-defined]
    parsed = yaml.safe_load(text)
    # Decimal fields converted to float so YAML doesn't emit !!python/object
    assert isinstance(parsed["model"]["input_per_1m_usd"], float)
    assert isinstance(parsed["model"]["output_per_1m_usd"], float)
