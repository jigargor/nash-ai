from __future__ import annotations

from app.agent.judge_feedback.contracts import JudgeGateMetrics
from app.agent.judge_feedback.policy_engine import authorize_threshold_lowering


def test_authorize_threshold_lowering_allows_without_judge_config() -> None:
    allowed, reason = authorize_threshold_lowering(
        judge_metrics=None,
        min_judge_samples=40,
        max_judge_false_negative_rate=15,
        max_judge_false_positive_rate=25,
        max_judge_inconclusive_rate=20,
        min_judge_reliability_for_lowering=82,
    )
    assert allowed is True
    assert reason == "judge_not_configured"


def test_authorize_threshold_lowering_rejects_provider_mismatch() -> None:
    allowed, reason = authorize_threshold_lowering(
        judge_metrics=JudgeGateMetrics(
            is_available=True,
            provider_independent=False,
            sample_size=100,
            false_negative_rate=0.01,
            false_positive_rate=0.01,
            inconclusive_rate=0.01,
            reliability_score=0.90,
        ),
        min_judge_samples=40,
        max_judge_false_negative_rate=15,
        max_judge_false_positive_rate=25,
        max_judge_inconclusive_rate=20,
        min_judge_reliability_for_lowering=82,
    )
    assert allowed is False
    assert reason == "provider_mismatch"


def test_authorize_threshold_lowering_rejects_high_false_negative_rate() -> None:
    allowed, reason = authorize_threshold_lowering(
        judge_metrics=JudgeGateMetrics(
            is_available=True,
            provider_independent=True,
            sample_size=100,
            false_negative_rate=0.16,
            false_positive_rate=0.01,
            inconclusive_rate=0.01,
            reliability_score=0.90,
        ),
        min_judge_samples=40,
        max_judge_false_negative_rate=15,
        max_judge_false_positive_rate=25,
        max_judge_inconclusive_rate=20,
        min_judge_reliability_for_lowering=82,
    )
    assert allowed is False
    assert reason == "fn_rate_too_high"


def test_authorize_threshold_lowering_accepts_healthy_metrics() -> None:
    allowed, reason = authorize_threshold_lowering(
        judge_metrics=JudgeGateMetrics(
            is_available=True,
            provider_independent=True,
            sample_size=100,
            false_negative_rate=0.01,
            false_positive_rate=0.01,
            inconclusive_rate=0.01,
            reliability_score=0.90,
        ),
        min_judge_samples=40,
        max_judge_false_negative_rate=15,
        max_judge_false_positive_rate=25,
        max_judge_inconclusive_rate=20,
        min_judge_reliability_for_lowering=82,
    )
    assert allowed is True
    assert reason == "judge_gate_healthy"

