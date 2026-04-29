"""Shared golden-dataset matching logic for eval harnesses."""

from __future__ import annotations

from dataclasses import dataclass

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass
class EvalTotals:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    clean_cases: int = 0
    clean_cases_with_fp: int = 0


def severity_matches(expected: str, actual: str) -> bool:
    if expected not in SEVERITY_ORDER or actual not in SEVERITY_ORDER:
        return False
    return abs(SEVERITY_ORDER[expected] - SEVERITY_ORDER[actual]) <= 1


def finding_matches(expected: dict, actual: dict) -> bool:
    expected_line = int(expected["line_start"])
    actual_line = int(actual["line_start"])
    return (
        expected["file_path"] == actual["file_path"]
        and abs(expected_line - actual_line) <= 3
        and expected["category"] == actual["category"]
        and severity_matches(str(expected["severity"]), str(actual["severity"]))
    )


def evaluate_case(expected_findings: list[dict], predicted_findings: list[dict], totals: EvalTotals) -> None:
    matched_predictions: set[int] = set()
    if not expected_findings:
        totals.clean_cases += 1
        if predicted_findings:
            totals.clean_cases_with_fp += 1
            totals.false_positive += len(predicted_findings)
        return

    for expected in expected_findings:
        match_index = None
        for idx, predicted in enumerate(predicted_findings):
            if idx in matched_predictions:
                continue
            if finding_matches(expected, predicted):
                match_index = idx
                break
        if match_index is None:
            totals.false_negative += 1
            continue
        matched_predictions.add(match_index)
        totals.true_positive += 1

    totals.false_positive += len(predicted_findings) - len(matched_predictions)


def safe_divide(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
