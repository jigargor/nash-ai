"""Benchmark the external repository pattern analyzer against golden datasets.

Runs the same ``analyze_file_content`` + critical-finding filter used by the
public-repo external evaluation shards, writes prediction JSON compatible with
``run_eval.py``, and emits aggregate metrics.

Usage (repo root):

  python evals/run_external_benchmark.py
  python evals/run_eval.py --prompt-version external_pattern \\
      --predictions-dir evals/predictions/external_pattern

This measures overlap between regex-style findings and LLM-oriented golden
labels (often partial); use trends alongside full-model evals, not as a
replacement.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_SRC = _REPO_ROOT / "apps" / "api" / "src"
_EVALS_DIR = Path(__file__).resolve().parent
for _p in (_API_SRC, _EVALS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.agent.external.analyzer import analyze_file_content
from app.agent.external.synthesis import (
    ExternalCriticalFinding,
    dedupe_findings,
    is_critical_finding,
)

from metrics import EvalTotals, evaluate_case, safe_divide


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run external pattern analyzer on golden dataset fixtures.")
    p.add_argument("--prompt-version", default="external_pattern", help="Label for outputs and run_eval.")
    p.add_argument("--datasets-dir", default="evals/datasets", help="Golden datasets root.")
    p.add_argument(
        "--predictions-dir",
        default=None,
        help="Where to write <case_id>.json. Default: evals/predictions/<prompt-version>/",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Metrics JSON path. Default: evals/results/<prompt-version>.json",
    )
    return p.parse_args()


def _predictions_for_case(context: dict[str, object]) -> list[dict[str, object]]:
    files_raw = context.get("files")
    if not isinstance(files_raw, dict):
        return []
    candidates: list[ExternalCriticalFinding] = []
    for path, content in files_raw.items():
        if not isinstance(path, str) or not isinstance(content, str):
            continue
        for finding in analyze_file_content(path, content):
            candidate: ExternalCriticalFinding = {
                "category": finding.category,
                "severity": finding.severity,
                "title": finding.title,
                "message": finding.message,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "evidence": finding.evidence,
            }
            if is_critical_finding(candidate):
                candidates.append(candidate)
    deduped = dedupe_findings(candidates)
    return [dict(x) for x in deduped]


def main() -> None:
    args = _parse_args()
    datasets_dir = Path(args.datasets_dir)
    predictions_dir = Path(args.predictions_dir or f"evals/predictions/{args.prompt_version}")
    output_path = Path(args.output or f"evals/results/{args.prompt_version}.json")
    predictions_dir.mkdir(parents=True, exist_ok=True)

    totals = EvalTotals()
    per_case: list[dict[str, object]] = []

    for case_dir in sorted(p for p in datasets_dir.iterdir() if p.is_dir()):
        expected_path = case_dir / "expected.json"
        context_path = case_dir / "context.json"
        if not expected_path.exists() or not context_path.exists():
            continue
        expected_payload = json.loads(expected_path.read_text(encoding="utf-8"))
        context_payload = json.loads(context_path.read_text(encoding="utf-8"))
        expected_findings = list(expected_payload.get("findings", []))
        predicted_findings = _predictions_for_case(context_payload)

        pred_path = predictions_dir / f"{case_dir.name}.json"
        pred_path.write_text(
            json.dumps({"findings": predicted_findings}, indent=2),
            encoding="utf-8",
        )

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
        "pipeline": "external_pattern_analyzer",
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
