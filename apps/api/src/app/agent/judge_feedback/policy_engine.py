from __future__ import annotations

from app.agent.judge_feedback.contracts import JudgeGateMetrics


def authorize_threshold_lowering(
    *,
    judge_metrics: JudgeGateMetrics | None,
    min_judge_samples: int,
    max_judge_false_negative_rate: int,
    max_judge_false_positive_rate: int,
    max_judge_inconclusive_rate: int,
    min_judge_reliability_for_lowering: int,
) -> tuple[bool, str]:
    if judge_metrics is None:
        return True, "judge_not_configured"
    if not judge_metrics.is_available:
        return False, "judge_unavailable"
    if not judge_metrics.provider_independent:
        return False, "provider_mismatch"
    if judge_metrics.sample_size < min_judge_samples:
        return False, "judge_low_sample"
    if judge_metrics.false_negative_rate is None:
        return False, "judge_fn_missing"
    if judge_metrics.false_positive_rate is None:
        return False, "judge_fp_missing"
    if judge_metrics.inconclusive_rate is None:
        return False, "judge_inconclusive_missing"
    if judge_metrics.reliability_score is None:
        return False, "reliability_missing"

    if judge_metrics.false_negative_rate > (max_judge_false_negative_rate / 100.0):
        return False, "fn_rate_too_high"
    if judge_metrics.false_positive_rate > (max_judge_false_positive_rate / 100.0):
        return False, "fp_rate_too_high"
    if judge_metrics.inconclusive_rate > (max_judge_inconclusive_rate / 100.0):
        return False, "inconclusive_too_high"
    if judge_metrics.reliability_score < (min_judge_reliability_for_lowering / 100.0):
        return False, "reliability_below_min"
    return True, "judge_gate_healthy"

