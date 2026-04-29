from __future__ import annotations

from app.agent.threshold_tuner import decide_next_threshold


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
