import argparse
import json
from dataclasses import dataclass
from pathlib import Path

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass
class EvalTotals:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    clean_cases: int = 0
    clean_cases_with_fp: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run golden-dataset evaluation for review outputs.")
    parser.add_argument("--prompt-version", required=True, help="Prompt version label to evaluate.")
    parser.add_argument("--datasets-dir", default="evals/datasets", help="Datasets root directory.")
    parser.add_argument(
        "--predictions-dir",
        default=None,
        help="Directory of prediction files. Defaults to evals/predictions/<prompt-version>/",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write metrics JSON to this path. Defaults to evals/results/<prompt-version>.json",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def main() -> None:
    args = parse_args()
    datasets_dir = Path(args.datasets_dir)
    predictions_dir = Path(args.predictions_dir or f"evals/predictions/{args.prompt_version}")
    output_path = Path(args.output or f"evals/results/{args.prompt_version}.json")

    totals = EvalTotals()
    per_case: list[dict[str, object]] = []

    for case_dir in sorted(path for path in datasets_dir.iterdir() if path.is_dir()):
        expected_path = case_dir / "expected.json"
        prediction_path = predictions_dir / f"{case_dir.name}.json"
        if not expected_path.exists() or not prediction_path.exists():
            continue
        expected_payload = load_json(expected_path)
        prediction_payload = load_json(prediction_path)
        expected_findings = list(expected_payload.get("findings", []))
        predicted_findings = list(prediction_payload.get("findings", []))
        before = EvalTotals(
            true_positive=totals.true_positive,
            false_positive=totals.false_positive,
            false_negative=totals.false_negative,
            clean_cases=totals.clean_cases,
            clean_cases_with_fp=totals.clean_cases_with_fp,
        )
        evaluate_case(expected_findings, predicted_findings, totals)
        per_case.append(
            {
                "case_id": case_dir.name,
                "expected_findings": len(expected_findings),
                "predicted_findings": len(predicted_findings),
                "true_positive_delta": totals.true_positive - before.true_positive,
                "false_positive_delta": totals.false_positive - before.false_positive,
                "false_negative_delta": totals.false_negative - before.false_negative,
            }
        )

    precision = safe_divide(totals.true_positive, totals.true_positive + totals.false_positive)
    recall = safe_divide(totals.true_positive, totals.true_positive + totals.false_negative)
    fp_rate = safe_divide(totals.clean_cases_with_fp, totals.clean_cases)

    result = {
        "prompt_version": args.prompt_version,
        "totals": {
            "tp": totals.true_positive,
            "fp": totals.false_positive,
            "fn": totals.false_negative,
            "clean_cases": totals.clean_cases,
            "clean_cases_with_fp": totals.clean_cases_with_fp,
        },
        "metrics": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "fp_rate": round(fp_rate, 4),
        },
        "per_case": per_case,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
