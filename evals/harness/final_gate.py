"""Final gate: held-out critic (N=3 uncached, mean +/- sd) and blind pairwise vs the bare model.

    python evals/harness/final_gate.py            # requires ANTHROPIC_API_KEY; refuses otherwise
    python evals/harness/final_gate.py --dry-run  # records BLOCKED status without spending

Never posts. Held-out PRs are read with ``--role critic`` semantics only here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
for path in (REPO_ROOT, API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


async def run_final_gate(*, repeats: int, max_prs: int, judge_model: str) -> dict[str, Any]:
    from app.agent.pipeline import DryRunDeliverySink, review_pipeline
    from app.agent.finalize import finalize_review
    from app.agent.loop import run_agent
    from app.ingestion import load_pr_context
    from evals.harness.baseline import run_bare_baseline
    from evals.harness.budget import PROJECTED_USD_PER_PR, check_projected_spend, record_spend
    from evals.harness.github_reader import CachedGitHubReader
    from evals.harness.judges import score_from_metrics
    from evals.harness.metrics import compute_run_metrics
    from evals.harness.pairwise import blind_pairwise, wilson_lower_bound
    from evals.harness.report import new_run_dir, write_run_artifacts
    from evals.harness.run import load_heldout

    heldout = sorted(load_heldout())[:max_prs]
    if not heldout:
        raise SystemExit("heldout.json is empty; run evals/harness/run.py once to populate it")
    # Each PR: N uncached pipeline runs + 1 baseline + 1 judge call (~2x a review).
    check_projected_spend(PROJECTED_USD_PER_PR * len(heldout) * (repeats + 2))

    gh = CachedGitHubReader()
    scores: list[float] = []
    wins = 0
    ties = 0
    comparisons = 0
    errors = 0
    total_cost = 0.0
    per_pr: list[dict[str, Any]] = []
    for repo_full, number in heldout:
        owner, repo = repo_full.split("/", 1)
        pr = await load_pr_context(gh, owner=owner, repo=repo, pr_number=number, max_prefetch_files=12)
        pr_scores: list[float] = []
        last_result = None
        for repeat in range(repeats):
            sink = DryRunDeliverySink()
            report = await review_pipeline(
                pr,
                delivery=sink,
                dry_run=True,
                agent_runner=run_agent,  # uncached on purpose: variance measurement
                finalizer=finalize_review,
            )
            total_cost += float(report.cost_usd or 0.0)
            dumped = report.model_dump(mode="json")
            metrics = compute_run_metrics(
                report=dumped,
                files_at_head=pr.files_at_head,
                commentable_lines=list(pr.commentable_lines),
            )
            critic = score_from_metrics(metrics)
            run_dir = new_run_dir(f"final-{repo}-{number}-r{repeat + 1}")
            write_run_artifacts(
                run_dir,
                findings=dumped,
                metrics=metrics,
                rendered_comments=sink.render_markdown(),
                meta={"repo": repo_full, "pr": number, "heldout": True, "repeat": repeat + 1, "critic": critic},
            )
            if report.pipeline_errors:
                errors += 1
            if critic.get("score") is not None:
                pr_scores.append(float(critic["score"]))
            last_result = report.result
        scores.extend(pr_scores)
        baseline = await run_bare_baseline(pr)
        if last_result is not None:
            verdict = await blind_pairwise(
                diff_text=pr.diff_text,
                review_a=last_result,
                review_b=baseline,
                judge_model=judge_model,
                seed=number,
            )
            comparisons += 1
            if verdict.get("winner") == "A":
                wins += 1
            elif verdict.get("winner") == "tie":
                ties += 1
        else:
            verdict = {"winner": "error"}
        per_pr.append(
            {
                "pr": number,
                "scores": pr_scores,
                "pairwise": verdict.get("winner"),
                "reason": verdict.get("reason"),
            }
        )
    record_spend(total_cost)
    mean = round(statistics.fmean(scores), 2) if scores else None
    sd = round(statistics.pstdev(scores), 2) if len(scores) > 1 else 0.0
    lower = wilson_lower_bound(wins, comparisons) if comparisons else 0.0
    return {
        "status": "complete",
        "heldout_prs": [n for _, n in heldout],
        "repeats": repeats,
        "critic_mean": mean,
        "critic_sd": sd,
        "pipeline_error_runs": errors,
        "pairwise": {
            "wins": wins,
            "ties": ties,
            "comparisons": comparisons,
            "win_rate": (wins / comparisons) if comparisons else None,
            "wilson_lower_95": round(lower, 3),
            "verdict": "scaffolding_beats_bare_model" if lower > 0.5 else "not_significant",
        },
        "spend_usd": round(total_cost, 4),
        "per_pr": per_pr,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Final gate on held-out PRs")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-prs", type=int, default=10)
    parser.add_argument("--judge-model", default="claude-opus-5")
    parser.add_argument("--dry-run", action="store_true", help="Record blocked status without spending.")
    args = parser.parse_args(argv)

    from evals.harness.run import provider_key_present
    from evals.harness.status import set_final_gate, set_pairwise

    if args.dry_run or not provider_key_present("anthropic"):
        payload = {
            "status": "blocked_no_llm_keys",
            "reason": "ANTHROPIC_API_KEY not configured in this environment; final gate needs live "
            "Sonnet 5 runs (N=3 uncached) and an Opus 5 judge.",
            "required": ["ANTHROPIC_API_KEY", "GITHUB_TOKEN (recommended for rate limits)"],
            "command": "python evals/harness/final_gate.py",
        }
        set_final_gate(payload)
        set_pairwise({"status": "blocked_no_llm_keys"})
        print(json.dumps(payload, indent=2))
        return 2
    payload = asyncio.run(run_final_gate(repeats=args.repeats, max_prs=args.max_prs, judge_model=args.judge_model))
    set_final_gate({k: v for k, v in payload.items() if k != "pairwise"})
    set_pairwise(payload["pairwise"])
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload["pipeline_error_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
