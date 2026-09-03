"""Main eval harness — dry-run by default; never posts to real repositories.

Modes (``--llm``):
  auto  -> ``live`` when a provider key is configured, otherwise ``stub`` (loud banner)
  live  -> real model calls through the LLM response cache (cached reruns cost $0)
  stub  -> deterministic offline reviewer (pipeline plumbing only; never model evidence)

Per run writes ``evals/runs/<id>/{findings.json, trace.jsonl, metrics.json,
rendered_comments.md, golden_diff.json, meta.json}``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

HELDOUT_PATH = REPO_ROOT / "evals" / "datasets" / "heldout.json"
DEFAULT_OWNER = "jigargor"
DEFAULT_REPO = "gentle-stream"
HELDOUT_BUCKETS = 3  # ~1/3 of the corpus is held out (~10 of ~30)


# ---------------------------------------------------------------------------
# LLM mode resolution
# ---------------------------------------------------------------------------


def provider_key_present(provider: str = "anthropic") -> bool:
    env_name = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}[
        provider
    ]
    if os.environ.get(env_name):
        return True
    try:
        from app.config import settings

        return bool(getattr(settings, f"{provider}_api_key", None))
    except Exception:
        return False


def resolve_llm_mode(requested: str, provider: str) -> str:
    if requested == "auto":
        return "live" if provider_key_present(provider) else "stub"
    if requested == "live" and not provider_key_present(provider):
        raise SystemExit(f"--llm live requested but no API key for provider {provider!r} is configured")
    return requested


# ---------------------------------------------------------------------------
# Held-out selection (deterministic hash of repo#number)
# ---------------------------------------------------------------------------


def is_heldout_number(repo_full: str, number: int) -> bool:
    digest = hashlib.sha256(f"{repo_full}#{number}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % HELDOUT_BUCKETS == 0


def load_heldout() -> set[tuple[str, int]]:
    if not HELDOUT_PATH.exists():
        return set()
    payload = json.loads(HELDOUT_PATH.read_text(encoding="utf-8"))
    items = payload.get("prs") or []
    out: set[tuple[str, int]] = set()
    for item in items:
        if isinstance(item, dict):
            repo = str(item.get("repo") or payload.get("repo") or "")
            number = int(item.get("pr") or item.get("number") or 0)
            if repo and number:
                out.add((repo, number))
    return out


def populate_heldout(repo_full: str, numbers: list[int]) -> set[tuple[str, int]]:
    """Write heldout.json once from the first real PR listing; idempotent afterwards."""
    existing = load_heldout()
    if existing:
        return existing
    chosen = sorted(n for n in numbers if is_heldout_number(repo_full, n))
    payload = {
        "version": 1,
        "repo": repo_full,
        "selection": (
            f"sha256('{{repo}}#{{number}}') first 8 hex digits % {HELDOUT_BUCKETS} == 0; "
            "frozen at first listing"
        ),
        "prs": [{"repo": repo_full, "pr": n} for n in chosen],
    }
    HELDOUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {(repo_full, n) for n in chosen}


# ---------------------------------------------------------------------------
# Local fixture cases
# ---------------------------------------------------------------------------


def local_case_to_pr_context(case_dir: Path):  # type: ignore[no-untyped-def]
    from app.agent.diff_parser import parse_diff, right_side_diff_line_set
    from app.agent.schema import PRContext

    context_path = case_dir / "context.json"
    context_payload: dict[str, Any] = {}
    if context_path.exists():
        loaded = json.loads(context_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            context_payload = loaded
    repo = str(context_payload.get("repo") or f"offline/{case_dir.name}")
    owner, name = (repo.split("/", 1) + ["offline"])[:2]
    diff_path = case_dir / "diff.patch"
    diff_text = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""
    files_raw = context_payload.get("files") or {}
    files = files_raw if isinstance(files_raw, dict) else {}
    try:
        commentable = sorted(right_side_diff_line_set(parse_diff(diff_text)))
    except Exception as exc:  # malformed fixture diff: pipeline records the ingestion error
        print(json.dumps({"case_id": case_dir.name, "fixture_warning": f"diff parse failed: {exc}"}))
        commentable = []
    return PRContext(
        owner=owner or "offline",
        repo=name or case_dir.name,
        pr_number=max(int(context_payload.get("pr_number") or 1), 1),
        head_sha=str(context_payload.get("head_sha") or "offline-sha"),
        title=str(context_payload.get("title") or case_dir.name),
        body=str(context_payload.get("body") or ""),
        diff_text=diff_text,
        files_at_head={str(k): str(v) for k, v in files.items()},
        commentable_lines=commentable,
    )


def load_expected(case_dir: Path) -> list[dict[str, Any]]:
    expected_path = case_dir / "expected.json"
    if not expected_path.exists():
        return []
    payload = json.loads(expected_path.read_text(encoding="utf-8"))
    return list(payload.get("findings") or [])


# ---------------------------------------------------------------------------
# One pipeline run
# ---------------------------------------------------------------------------


class HarnessRunner:
    def __init__(
        self,
        *,
        llm_mode: str,
        model_name: str | None,
        provider: str,
        effort: str,
        use_cache: bool,
        run_editor: bool,
    ) -> None:
        from evals.harness.llm_cache import LLMResponseCache

        self.llm_mode = llm_mode
        self.model_name = model_name
        self.provider = provider
        self.effort = effort
        self.run_editor = run_editor
        self.cache = LLMResponseCache(enabled=use_cache)
        self.total_cost_usd = 0.0
        self.run_dirs: list[Path] = []
        self.label: str | None = None

    def _llm_callables(self) -> tuple[Any, Any]:
        if self.llm_mode == "stub":
            from evals.harness.stub_llm import stub_agent_runner, stub_finalizer

            return stub_agent_runner, stub_finalizer
        from app.agent.finalize import finalize_review
        from app.agent.loop import run_agent
        from evals.harness.llm_cache import cached_agent_runner, cached_finalizer

        return cached_agent_runner(run_agent, self.cache), cached_finalizer(finalize_review, self.cache)

    async def run_one(
        self,
        pr_context: Any,
        *,
        run_label: str,
        expected: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.agent.pipeline import DryRunDeliverySink, review_pipeline
        from app.observability import InMemoryTestSink, JsonlSink, configure_observer, reset_observer
        from evals.harness.judges import score_from_metrics
        from evals.harness.metrics import compute_run_metrics, golden_scores
        from evals.harness.report import new_run_dir, write_run_artifacts

        run_dir = new_run_dir(f"{self.label}__{run_label}" if self.label else run_label)
        memory_sink = InMemoryTestSink()
        configure_observer([memory_sink, JsonlSink(str(run_dir / "trace.jsonl"))], enabled=True)
        agent_runner, finalizer = self._llm_callables()
        sink = DryRunDeliverySink()
        try:
            report = await review_pipeline(
                pr_context,
                delivery=sink,
                dry_run=True,  # evals never post
                model_name=self.model_name,
                provider=self.provider,
                agent_runner=agent_runner,
                finalizer=finalizer,
                run_editor_stage=self.run_editor,
                llm_effort=self.effort,
            )
        finally:
            reset_observer()

        dumped = report.model_dump(mode="json")
        cost = float(report.cost_usd or 0.0)
        self.total_cost_usd += cost
        metrics = compute_run_metrics(
            report=dumped,
            files_at_head=pr_context.files_at_head,
            commentable_lines=list(pr_context.commentable_lines),
            expected_findings=expected,
        )
        metrics["llm_mode"] = str(dumped.get("debug_artifacts", {}).get("llm_mode") or self.llm_mode)
        metrics["cache"] = {"hits": self.cache.hits, "misses": self.cache.misses}
        metrics["observer_events"] = len(memory_sink.events)
        critic = score_from_metrics(metrics)
        golden_diff = (
            golden_scores(expected, dumped.get("result", {}).get("findings") or [])
            if expected is not None
            else None
        )
        run_meta = {
            "repo": pr_context.repo_full_name,
            "pr": pr_context.pr_number,
            "head_sha": pr_context.head_sha,
            "dry_run": True,
            "llm_mode": metrics["llm_mode"],
            "models_served": report.models_served,
            "critic": critic,
            **(meta or {}),
        }
        write_run_artifacts(
            run_dir,
            findings=dumped,
            metrics=metrics,
            rendered_comments=sink.render_markdown(),
            trace_events=None,  # JsonlSink already wrote trace.jsonl during the run
            golden_diff=golden_diff,
            meta=run_meta,
        )
        self.run_dirs.append(run_dir)
        return {
            "run_dir": str(run_dir),
            "metrics": metrics,
            "critic": critic,
            "finding_count": len(report.result.findings),
            "pipeline_errors": report.pipeline_errors,
            "degraded_stages": report.exceptions,
            "cost_usd": cost,
            "llm_mode": metrics["llm_mode"],
        }


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


async def run_local_datasets(runner: HarnessRunner, *, datasets_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case_dir in sorted(p for p in datasets_dir.iterdir() if p.is_dir()):
        if not (case_dir / "expected.json").exists():
            continue
        pr = local_case_to_pr_context(case_dir)
        expected = load_expected(case_dir)
        one = await runner.run_one(
            pr, run_label=case_dir.name, expected=expected, meta={"case_id": case_dir.name}
        )
        results.append({"case_id": case_dir.name, **one})
        print(
            json.dumps(
                {
                    "case_id": case_dir.name,
                    "llm_mode": one["llm_mode"],
                    "errors": one["pipeline_errors"],
                    "findings": one["finding_count"],
                    "score": one["critic"].get("score"),
                },
                default=str,
            )
        )
    return results


async def run_github_prs(
    runner: HarnessRunner,
    *,
    owner: str,
    repo: str,
    pr_numbers: list[int],
    role: str,
    max_prefetch_files: int,
    repeats: int,
) -> list[dict[str, Any]]:
    from app.ingestion import load_pr_context
    from evals.harness.github_reader import CachedGitHubReader

    full = f"{owner}/{repo}"
    heldout = load_heldout()
    gh = CachedGitHubReader()
    results: list[dict[str, Any]] = []
    for number in pr_numbers:
        if (full, number) in heldout and role != "critic":
            print(f"SKIP held-out PR {full}#{number} (pass --role critic to run)")
            continue
        try:
            pr = await load_pr_context(
                gh, owner=owner, repo=repo, pr_number=number, max_prefetch_files=max_prefetch_files
            )
        except Exception as exc:  # ingestion failure is a pipeline error for this PR, not a crash
            message = f"ingestion.load_pr_context: {exc.__class__.__name__}: {str(exc)[:200]}"
            print(json.dumps({"pr": number, "errors": [message]}))
            results.append(
                {
                    "pr": number,
                    "repeat": 1,
                    "run_dir": None,
                    "metrics": {"pipeline_errors": 1, "pipeline_error_messages": [message]},
                    "critic": {"score": None, "open_issues": [message], "method": "none"},
                    "finding_count": 0,
                    "pipeline_errors": [message],
                    "degraded_stages": [],
                    "cost_usd": 0.0,
                    "llm_mode": runner.llm_mode,
                }
            )
            continue
        for repeat in range(max(1, repeats)):
            one = await runner.run_one(
                pr,
                run_label=f"{repo}-{number}" + (f"-r{repeat + 1}" if repeats > 1 else ""),
                meta={"repeat": repeat + 1, "heldout": (full, number) in heldout},
            )
            results.append({"pr": number, "repeat": repeat + 1, **one})
            print(
                json.dumps(
                    {
                        "pr": number,
                        "repeat": repeat + 1,
                        "llm_mode": one["llm_mode"],
                        "errors": one["pipeline_errors"],
                        "findings": one["finding_count"],
                        "cross_check_warnings": one["metrics"].get("diff_cross_check_warnings"),
                        "score": one["critic"].get("score"),
                    },
                    default=str,
                )
            )
    print(json.dumps({"github_reader": {"cache_hits": gh.cache_hits, "network_calls": gh.network_calls}}))
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nash AI eval harness (dry-run default)")
    parser.add_argument("--datasets-dir", default=str(REPO_ROOT / "evals" / "datasets"))
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--pr", type=int, action="append", default=[])
    parser.add_argument("--limit-prs", type=int, default=5)
    parser.add_argument("--local-only", action="store_true", help="Only run fixture datasets (no GitHub).")
    parser.add_argument("--skip-local", action="store_true", help="Skip fixture datasets.")
    parser.add_argument("--role", choices=["builder", "critic"], default="builder")
    parser.add_argument("--llm", choices=["auto", "live", "stub"], default="auto")
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--editor", action="store_true", help="Run the editor stage too.")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the LLM response cache.")
    parser.add_argument("--repeats", type=int, default=1, help="Uncached repeats per PR (variance).")
    parser.add_argument("--max-prefetch-files", type=int, default=12)
    parser.add_argument("--round-budget-usd", type=float, default=25.0)
    parser.add_argument("--label", default=None, help="Aggregate summary label.")
    parser.add_argument(
        "--post",
        action="store_true",
        help="Forbidden on eval PRs. Harness ignores this flag and always dry-runs.",
    )
    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    if args.post:
        print("REFUSING --post: evals never post to real repositories. Continuing in dry-run.")
    from evals.harness.budget import (
        PROJECTED_USD_PER_PR,
        allocate_round_budget,
        check_projected_spend,
        record_spend,
    )
    from evals.harness.status import load_status

    llm_mode = resolve_llm_mode(args.llm, args.provider)
    if llm_mode == "stub":
        print(
            "=" * 78
            + "\nLLM MODE: stub - no provider API key configured. This exercises pipeline plumbing "
            "only.\nScores from this run are NOT model quality evidence and are recorded as such.\n"
            + "=" * 78
        )
    runner = HarnessRunner(
        llm_mode=llm_mode,
        model_name=args.model,
        provider=args.provider,
        effort=args.effort,
        use_cache=not args.no_cache,
        run_editor=args.editor,
    )
    runner.label = args.label

    results: list[dict[str, Any]] = []
    if not args.skip_local:
        results.extend(await run_local_datasets(runner, datasets_dir=Path(args.datasets_dir)))

    pr_numbers: list[int] = []
    if not args.local_only:
        from evals.harness.github_reader import CachedGitHubReader

        gh = CachedGitHubReader()
        pr_numbers = list(args.pr)
        listed = await gh.list_pull_requests(args.owner, args.repo, state="all", per_page=30)
        all_numbers = [int(item["number"]) for item in listed if "number" in item]
        heldout = populate_heldout(f"{args.owner}/{args.repo}", all_numbers)
        if not pr_numbers:
            candidates = [n for n in all_numbers if (f"{args.owner}/{args.repo}", n) not in heldout]
            if args.role == "critic":
                candidates = [n for n in all_numbers if (f"{args.owner}/{args.repo}", n) in heldout]
            pr_numbers = candidates[: args.limit_prs]
        if llm_mode == "live":
            status = load_status()
            round_id = int(status.get("current_round") or 1)
            allocate_round_budget(args.round_budget_usd, round_id=round_id)
            check_projected_spend(PROJECTED_USD_PER_PR * len(pr_numbers) * max(1, args.repeats))
        results.extend(
            await run_github_prs(
                runner,
                owner=args.owner,
                repo=args.repo,
                pr_numbers=pr_numbers,
                role=args.role,
                max_prefetch_files=args.max_prefetch_files,
                repeats=args.repeats,
            )
        )
    if llm_mode == "live" and runner.total_cost_usd:
        record_spend(runner.total_cost_usd)

    summary = summarize(results, llm_mode=llm_mode, label=args.label)
    print(json.dumps({"summary": summary}, indent=2, default=str))
    runs_root = REPO_ROOT / "evals" / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    (runs_root / "latest_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    if args.label:
        (runs_root / f"aggregate-{args.label}.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
    if not results:
        print("No runs executed.")
        return 1
    return 0 if summary["pipeline_error_runs"] == 0 else 1


def summarize(results: list[dict[str, Any]], *, llm_mode: str, label: str | None) -> dict[str, Any]:
    from evals.harness.judges import aggregate_critic
    from evals.harness.status import now_iso

    critics = [r["critic"] for r in results if r.get("critic")]
    aggregate = aggregate_critic(critics) if critics else {}
    total_cost = round(sum(float(r.get("cost_usd") or 0.0) for r in results), 6)
    cache_hits = sum(int((r.get("metrics") or {}).get("cache", {}).get("hits", 0)) for r in results)
    findings_total = sum(int(r.get("finding_count") or 0) for r in results)
    drop_reasons: dict[str, int] = {}
    for r in results:
        for reason, count in ((r.get("metrics") or {}).get("drop_reasons") or {}).items():
            drop_reasons[reason] = drop_reasons.get(reason, 0) + int(count)
    return {
        "label": label,
        "generated_at": now_iso(),
        "llm_mode": llm_mode,
        "runs": len(results),
        "pipeline_error_runs": sum(1 for r in results if r.get("pipeline_errors")),
        "degraded_stage_runs": sum(1 for r in results if r.get("degraded_stages")),
        "findings_total": findings_total,
        "drop_reasons": drop_reasons,
        "total_cost_usd": total_cost,
        "cache_hits": cache_hits,
        "aggregate_critic": aggregate,
        "results": [
            {
                "id": r.get("case_id") or r.get("pr"),
                "run_dir": r.get("run_dir"),
                "errors": r.get("pipeline_errors"),
                "degraded": r.get("degraded_stages"),
                "findings": r.get("finding_count"),
                "score": (r.get("critic") or {}).get("score"),
                "cost_usd": r.get("cost_usd"),
                "llm_mode": r.get("llm_mode"),
            }
            for r in results
        ],
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
