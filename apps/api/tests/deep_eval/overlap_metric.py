from __future__ import annotations

import json
from typing import Any

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase


def _import_eval_metrics() -> tuple[Any, Any, Any]:
    from evals.metrics import EvalTotals, evaluate_case, safe_divide

    return EvalTotals, evaluate_case, safe_divide


class FindingOverlapMetric(BaseMetric):
    _required_params = []

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self.score = 0.0
        self.reason = ""
        self.success = False
        self.include_reason = True
        self.async_mode = False
        self.verbose_mode = False

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        EvalTotals, evaluate_case, safe_divide = _import_eval_metrics()
        try:
            expected_payload = json.loads(test_case.expected_output or "{}")
        except json.JSONDecodeError:
            expected_payload = {}
        try:
            predicted_payload = json.loads(test_case.actual_output or "{}")
        except json.JSONDecodeError:
            predicted_payload = {}
        expected_findings = list(expected_payload.get("findings", []))
        predicted_findings = list(predicted_payload.get("findings", []))

        totals = EvalTotals()
        evaluate_case(expected_findings, predicted_findings, totals)
        precision = safe_divide(totals.true_positive, totals.true_positive + totals.false_positive)
        recall = safe_divide(totals.true_positive, totals.true_positive + totals.false_negative)
        self.score = recall
        self.success = bool(recall >= self.threshold and precision >= 0.5)
        self.reason = (
            f"recall={recall:.3f}, precision={precision:.3f}, "
            f"tp={totals.true_positive}, fp={totals.false_positive}, fn={totals.false_negative}"
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)
