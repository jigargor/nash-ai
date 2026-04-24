import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two eval result files.")
    parser.add_argument("baseline", help="Path to baseline eval JSON")
    parser.add_argument("candidate", help="Path to candidate eval JSON")
    parser.add_argument("--max-precision-drop", type=float, default=0.05)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    baseline = load_json(args.baseline)
    candidate = load_json(args.candidate)

    base_metrics = baseline.get("metrics", {})
    cand_metrics = candidate.get("metrics", {})
    precision_delta = float(cand_metrics.get("precision", 0.0)) - float(base_metrics.get("precision", 0.0))
    recall_delta = float(cand_metrics.get("recall", 0.0)) - float(base_metrics.get("recall", 0.0))
    fp_rate_delta = float(cand_metrics.get("fp_rate", 0.0)) - float(base_metrics.get("fp_rate", 0.0))

    passed = precision_delta >= (0 - args.max_precision_drop)
    summary = {
        "baseline_prompt_version": baseline.get("prompt_version"),
        "candidate_prompt_version": candidate.get("prompt_version"),
        "precision_delta": round(precision_delta, 4),
        "recall_delta": round(recall_delta, 4),
        "fp_rate_delta": round(fp_rate_delta, 4),
        "max_precision_drop": args.max_precision_drop,
        "passed": passed,
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    if not passed:
        raise SystemExit("Precision regression exceeded threshold")


if __name__ == "__main__":
    main()
