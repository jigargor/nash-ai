"""/loop driver: resume from the lowest-scoring module until all pass or budget is exhausted.

Each iteration:
  1. pick the lowest-scoring module (unscored counts as lowest; ties -> earliest wave);
  2. write the round budget to docs/STATUS.json BEFORE any spend;
  3. run the harness (fixtures + tuning PRs; held-out PRs are never touched here);
  4. run the fresh-context critic for that module and persist scores/issues/rounds/spend;
  5. stop when every module passes, the budget is exhausted, or --max-iterations is hit.

    python evals/harness/loop.py --max-iterations 4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
for path in (REPO_ROOT, API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _run(cmd: list[str]) -> int:
    print("$", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Critic loop driver")
    parser.add_argument("--max-iterations", type=int, default=4)
    parser.add_argument("--round-budget-usd", type=float, default=25.0)
    parser.add_argument("--limit-prs", type=int, default=6)
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args(argv)

    from evals.harness.budget import allocate_round_budget
    from evals.harness.run import provider_key_present
    from evals.harness.status import (
        all_modules_pass,
        append_note,
        load_status,
        lowest_scoring_module,
        save_status,
    )

    live = provider_key_present("anthropic")
    python = sys.executable
    history: list[dict[str, Any]] = []
    for iteration in range(1, args.max_iterations + 1):
        status = load_status()
        if all_modules_pass(status):
            print("All modules pass; loop complete.")
            break
        module = lowest_scoring_module(status)
        if module is None:
            print("No module is eligible for another round (all passed or at the 4-round cap).")
            break
        round_n = int((status.get("modules", {}).get(module) or {}).get("rounds") or 0) + 1
        current_round = int(status.get("current_round") or 0) + 1
        try:
            allocate_round_budget(args.round_budget_usd if live else 0.0, round_id=current_round)
        except RuntimeError as exc:
            append_note(f"loop stopped: {exc}")
            print(f"Budget exhausted: {exc}")
            break
        status = load_status()
        status["current_wave"] = status.get("current_wave") or 1
        status["loop"] = {"iteration": iteration, "module": module, "round": round_n, "live": live}
        save_status(status)

        harness_cmd = [
            python,
            str(REPO_ROOT / "evals" / "harness" / "run.py"),
            "--label",
            f"loop-{module}-r{round_n}",
            "--limit-prs",
            str(args.limit_prs),
            "--llm",
            "auto",
        ]
        if args.local_only:
            harness_cmd.append("--local-only")
        harness_rc = _run(harness_cmd)
        critic_rc = _run(
            [
                python,
                str(REPO_ROOT / "evals" / "harness" / "critic.py"),
                "--module",
                module,
                "--round",
                str(round_n),
                "--label",
                f"loop-{module}-r{round_n}",
            ]
        )
        status = load_status()
        entry = (status.get("modules") or {}).get(module) or {}
        history.append(
            {
                "iteration": iteration,
                "module": module,
                "round": round_n,
                "harness_rc": harness_rc,
                "critic_rc": critic_rc,
                "score": entry.get("score"),
                "status": entry.get("status"),
                "open_issues": (entry.get("open_issues") or [])[:3],
            }
        )
        if not live:
            append_note(
                "loop ran in offline stub mode: no provider API key in this environment, so module "
                "scores are smoke-only and cannot pass the >=8.5 critic gate honestly."
            )
            print("Offline stub mode: one smoke iteration is meaningful; stopping to avoid fake rounds.")
            break

    status = load_status()
    status["loop_history"] = (status.get("loop_history") or []) + history
    save_status(status)
    print(json.dumps({"loop_history": history, "all_pass": all_modules_pass(status)}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
