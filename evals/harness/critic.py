"""Fresh-context critic gauntlet for one module.

Input is ONLY ``evals/runs/<id>/`` artifacts plus the rubric; the critic never sees code.
Output: ``evals/critic/<module>/round-N.json`` and the module entry in ``docs/STATUS.json``.

    python evals/harness/critic.py --module validation --round 1
    python evals/harness/critic.py --module pipeline --round 2 --since 20260903T00

Without an Anthropic key the LLM critic is unavailable; the deterministic metrics proxy is
recorded with ``llm_backed: false`` and the module status stays ``smoke_only_blocked_no_llm_keys``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
for path in (REPO_ROOT, API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

RUNS_ROOT = REPO_ROOT / "evals" / "runs"

# Which run artifacts each module is judged on (all modules see the same runs; the rubric
# weights are shared, the module name only scopes the issue list and STATUS entry).
MODULES = [
    "evals",
    "telemetry",
    "infra",
    "pipeline",
    "ingestion",
    "context-packaging",
    "agent-core",
    "validation",
    "prompts",
    "delivery",
    "frontend",
]


def select_run_dirs(*, since: str | None, label: str | None, limit: int) -> list[Path]:
    dirs = [p for p in RUNS_ROOT.iterdir() if p.is_dir() and (p / "metrics.json").exists()]
    if since:
        dirs = [p for p in dirs if p.name >= since]
    if label:
        dirs = [p for p in dirs if label in p.name]
    dirs.sort(key=lambda p: p.name)
    return dirs[-limit:]


async def run_critic(module: str, round_n: int, run_dirs: list[Path], *, use_llm: bool) -> dict[str, Any]:
    from evals.harness.judges import aggregate_critic, llm_critic, score_from_metrics, write_critic_result
    from evals.harness.status import record_module_round

    per_run: list[dict[str, Any]] = []
    llm_modes: set[str] = set()
    for run_dir in run_dirs:
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        llm_modes.add(str(metrics.get("llm_mode") or "unknown"))
        verdict: dict[str, Any] | None = None
        if use_llm:
            verdict = await llm_critic(run_dir, module=module)
        if verdict is None:
            verdict = score_from_metrics(metrics)
        verdict["run_dir"] = str(run_dir)
        per_run.append(verdict)

    aggregate = aggregate_critic(per_run)
    model_evidence = llm_modes <= {"live", "cache", "live+cache"} and bool(llm_modes)
    evidence_llm_backed = bool(aggregate.get("llm_backed")) and model_evidence
    payload = {
        "module": module,
        "round": round_n,
        "run_dirs": [str(p) for p in run_dirs],
        "llm_modes_seen": sorted(llm_modes),
        "reviewed_model_output": model_evidence,
        "critic_llm_backed": bool(aggregate.get("llm_backed")),
        "aggregate": aggregate,
        "per_run": per_run,
        "verdict": (
            "PASS"
            if aggregate.get("pass") and evidence_llm_backed
            else "BLOCKED_NO_LLM_KEYS"
            if not evidence_llm_backed
            else "FAIL"
        ),
        "rubric_weights": {"anchoring": 25, "suggestion_validity": 20, "severity_calibration": 15, "groundedness": 20, "noise_fp": 15},
    }
    path = write_critic_result(module, round_n, payload, REPO_ROOT)
    record_module_round(
        module,
        score=aggregate.get("score"),
        passed=bool(aggregate.get("pass")),
        open_issues=list(aggregate.get("open_issues") or []),
        method=str(aggregate.get("method")),
        round_n=round_n,
        artifacts=[str(path)],
        evidence_llm_backed=evidence_llm_backed,
    )
    payload["critic_path"] = str(path)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fresh-context critic over harness artifacts")
    parser.add_argument("--module", choices=MODULES, required=True)
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--since", default=None, help="Only runs whose dir name >= this prefix.")
    parser.add_argument("--label", default=None, help="Only runs whose dir name contains this label.")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--no-llm", action="store_true", help="Force the metrics proxy critic.")
    args = parser.parse_args(argv)

    run_dirs = select_run_dirs(since=args.since, label=args.label, limit=args.limit)
    if not run_dirs:
        print("No harness runs found; run evals/harness/run.py first.")
        return 1
    payload = asyncio.run(run_critic(args.module, args.round, run_dirs, use_llm=not args.no_llm))
    summary = {
        "module": payload["module"],
        "round": payload["round"],
        "verdict": payload["verdict"],
        "score": payload["aggregate"].get("score"),
        "score_sd": payload["aggregate"].get("score_sd"),
        "runs": payload["aggregate"].get("runs"),
        "pipeline_error_runs": payload["aggregate"].get("pipeline_error_runs"),
        "llm_modes_seen": payload["llm_modes_seen"],
        "critic_path": payload["critic_path"],
        "top_issues": (payload["aggregate"].get("open_issues") or [])[:5],
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
