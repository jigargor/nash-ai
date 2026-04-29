from __future__ import annotations

import asyncio

import pytest

from app.agent.judge_feedback.contracts import JudgeGateMetrics
from app.agent import threshold_tuner
from app.agent.threshold_tuner import (
    _build_judge_gate_window_payload,
    _judge_metrics_from_assessment_rows,
    _judge_metrics_from_metadata,
    decide_next_threshold,
)


def test_decide_next_threshold_lowers_when_disagreement_is_low() -> None:
    threshold, action = decide_next_threshold(
        previous_threshold=90,
        minimum_threshold=70,
        step_down=2,
        target_disagreement_low=5,
        target_disagreement_high=15,
        max_false_accept_rate=5,
        max_dismiss_rate=25,
        disagreement_rate=0.02,
        dismiss_rate=0.01,
        false_accept_rate=0.02,
        sample_size=200,
        min_samples=100,
    )
    assert action == "lower_threshold"
    assert threshold == 88


def test_decide_next_threshold_raises_on_guardrail_breach() -> None:
    threshold, action = decide_next_threshold(
        previous_threshold=80,
        minimum_threshold=60,
        step_down=2,
        target_disagreement_low=5,
        target_disagreement_high=15,
        max_false_accept_rate=5,
        max_dismiss_rate=25,
        disagreement_rate=0.42,
        dismiss_rate=0.01,
        false_accept_rate=0.02,
        sample_size=220,
        min_samples=100,
    )
    assert action == "raise_or_rollback_guardrail"
    assert threshold == 82


def test_decide_next_threshold_holds_when_judge_gate_fails() -> None:
    threshold, action = decide_next_threshold(
        previous_threshold=90,
        minimum_threshold=70,
        step_down=2,
        target_disagreement_low=5,
        target_disagreement_high=15,
        max_false_accept_rate=5,
        max_dismiss_rate=25,
        disagreement_rate=0.02,
        dismiss_rate=0.01,
        false_accept_rate=0.02,
        sample_size=220,
        min_samples=100,
        judge_metrics=JudgeGateMetrics(
            is_available=True,
            provider_independent=False,
            sample_size=100,
            false_negative_rate=0.01,
            false_positive_rate=0.01,
            inconclusive_rate=0.05,
            reliability_score=0.95,
        ),
    )
    assert action == "hold_judge_gate_provider_mismatch"
    assert threshold == 90


def test_decide_next_threshold_lowers_when_judge_gate_is_healthy() -> None:
    threshold, action = decide_next_threshold(
        previous_threshold=90,
        minimum_threshold=70,
        step_down=2,
        target_disagreement_low=5,
        target_disagreement_high=15,
        max_false_accept_rate=5,
        max_dismiss_rate=25,
        disagreement_rate=0.02,
        dismiss_rate=0.01,
        false_accept_rate=0.02,
        sample_size=220,
        min_samples=100,
        judge_metrics=JudgeGateMetrics(
            is_available=True,
            provider_independent=True,
            sample_size=100,
            false_negative_rate=0.01,
            false_positive_rate=0.01,
            inconclusive_rate=0.05,
            reliability_score=0.95,
        ),
    )
    assert action == "lower_threshold"
    assert threshold == 88


def test_judge_metrics_from_metadata_parses_nested_payload() -> None:
    metrics = _judge_metrics_from_metadata(
        {
            "judge_gate_metrics": {
                "is_available": True,
                "provider_independent": True,
                "sample_size": 44,
                "false_negative_rate": 0.12,
                "false_positive_rate": 0.2,
                "inconclusive_rate": 0.1,
                "reliability_score": 0.86,
            }
        },
        require_provider_family_differ=True,
    )
    assert metrics.is_available is True
    assert metrics.provider_independent is True
    assert metrics.sample_size == 44
    assert metrics.false_negative_rate == 0.12
    assert metrics.false_positive_rate == 0.2
    assert metrics.inconclusive_rate == 0.1
    assert metrics.reliability_score == 0.86


def test_judge_metrics_from_metadata_infers_provider_independence_from_families() -> None:
    metrics = _judge_metrics_from_metadata(
        {
            "sample_size": 25,
            "judge_provider_family": "openai",
            "primary_provider_family": "anthropic",
        },
        require_provider_family_differ=True,
    )
    assert metrics.provider_independent is True
    assert metrics.sample_size == 25


def test_judge_metrics_from_metadata_defaults_to_not_independent_without_data() -> None:
    metrics = _judge_metrics_from_metadata(
        {"sample_size": 10},
        require_provider_family_differ=True,
    )
    assert metrics.provider_independent is False


def test_build_judge_gate_window_payload_defaults_when_metrics_missing() -> None:
    payload = _build_judge_gate_window_payload(
        judge_metrics=None,
        tuner_action="",
        recorded_at="2026-04-29T00:00:00Z",
    )
    metrics = payload["judge_gate_metrics"]
    assert isinstance(metrics, dict)
    assert metrics["is_available"] is False
    assert metrics["sample_size"] == 0
    assert payload["recorded_at"] == "2026-04-29T00:00:00Z"
    assert "tuner_action" not in payload


def test_publish_judge_gate_window_writes_normalized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_set_cached_judge_gate_window(
        installation_id: int, payload: dict[str, object]
    ) -> None:
        captured["installation_id"] = installation_id
        captured["payload"] = payload

    monkeypatch.setattr(
        threshold_tuner, "_set_cached_judge_gate_window", _fake_set_cached_judge_gate_window
    )

    metrics = JudgeGateMetrics(
        is_available=True,
        provider_independent=True,
        sample_size=77,
        false_negative_rate=0.07,
        false_positive_rate=0.12,
        inconclusive_rate=0.08,
        reliability_score=0.9,
    )
    payload = asyncio.run(
        threshold_tuner.publish_judge_gate_window(
            installation_id=42,
            judge_metrics=metrics,
            tuner_action="lower_threshold",
            recorded_at="2026-04-29T01:00:00Z",
            extra={"source": "unit_test"},
        )
    )

    assert captured["installation_id"] == 42
    stored_payload = captured["payload"]
    assert isinstance(stored_payload, dict)
    assert payload == stored_payload
    assert payload["tuner_action"] == "lower_threshold"
    assert payload["recorded_at"] == "2026-04-29T01:00:00Z"
    assert payload["source"] == "unit_test"
    judge_gate = payload["judge_gate_metrics"]
    assert isinstance(judge_gate, dict)
    assert judge_gate["sample_size"] == 77


def test_judge_metrics_from_assessment_rows_aggregates_labels() -> None:
    metrics = _judge_metrics_from_assessment_rows(
        [
            {
                "quality_label": "missed_material_issue",
                "judge_reliability_score": 0.88,
                "judge_provider_family": "openai",
                "primary_provider_family": "anthropic",
            },
            {"quality_label": "posted_false_positive"},
            {"quality_label": "inconclusive"},
            {"quality_label": "acceptable"},
        ],
        require_provider_family_differ=True,
    )
    assert metrics.is_available is True
    assert metrics.provider_independent is True
    assert metrics.sample_size == 4
    assert metrics.false_negative_rate == pytest.approx(0.25)
    assert metrics.false_positive_rate == pytest.approx(0.25)
    assert metrics.inconclusive_rate == pytest.approx(0.25)
    assert metrics.reliability_score == pytest.approx(0.88)


def test_judge_metrics_from_assessment_rows_handles_empty_rows() -> None:
    metrics = _judge_metrics_from_assessment_rows([], require_provider_family_differ=True)
    assert metrics.is_available is False
    assert metrics.sample_size == 0
