import argparse
import json
import sys
from pathlib import Path

_EVALS_DIR = Path(__file__).resolve().parent
if str(_EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVALS_DIR))

from metrics import EvalTotals, evaluate_case, safe_divide


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
