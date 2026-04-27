"""
Enforce per-module coverage thresholds from a coverage.py JSON report.

Usage:
    python scripts/check_coverage.py coverage.json coverage_thresholds.json

Exits 1 if any module falls below its declared threshold.
"""
import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <coverage.json> <thresholds.json>", file=sys.stderr)
        sys.exit(2)

    report_path = Path(sys.argv[1])
    thresholds_path = Path(sys.argv[2])

    files: dict = json.loads(report_path.read_text(encoding="utf-8"))["files"]
    modules: list[dict] = json.loads(thresholds_path.read_text(encoding="utf-8"))["modules"]

    failures: list[str] = []

    for m in modules:
        prefix: str = m["prefix"]
        min_cov: int = m["min"]
        label: str = m["label"]

        relevant = {k: v for k, v in files.items() if k.startswith(prefix)}
        if not relevant:
            print(f"  SKIP  {label:<22} ({prefix}) — no files matched")
            continue

        stmts = sum(v["summary"]["num_statements"] for v in relevant.values())
        covered = sum(v["summary"]["covered_lines"] for v in relevant.values())
        pct = round(covered / stmts * 100, 1) if stmts else 100.0
        passed = pct >= min_cov

        flag = "PASS" if passed else "FAIL"
        print(f"  {flag}  {label:<22} {pct:5.1f}%  (threshold: {min_cov}%,  files: {len(relevant)})")

        if not passed:
            failures.append(f"{label} ({prefix}): {pct}% < {min_cov}% required")

    print()
    if failures:
        print(f"Coverage check FAILED — {len(failures)} module(s) below threshold:")
        for f in failures:
            print(f"  • {f}")
        sys.exit(1)

    print(f"Coverage check PASSED — all {len(modules)} modules meet their thresholds.")


if __name__ == "__main__":
    main()
