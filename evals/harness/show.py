"""Showcase CLI — dump context / validate / prompt / render without posting."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))


async def cmd_context(owner: str, repo: str, pr: int) -> None:
    from app.ingestion import load_pr_context
    from evals.harness.github_reader import CachedGitHubReader

    gh = CachedGitHubReader()
    ctx = await load_pr_context(gh, owner=owner, repo=repo, pr_number=pr)
    print(json.dumps(ctx.model_dump(mode="json"), indent=2)[:50_000])


async def cmd_prompt(owner: str, repo: str, pr: int) -> None:
    from app.agent.pipeline.review_pipeline import _build_user_prompt
    from app.agent.prompts.system import build_system_prompt
    from app.ingestion import load_pr_context
    from evals.harness.github_reader import CachedGitHubReader

    gh = CachedGitHubReader()
    ctx = await load_pr_context(gh, owner=owner, repo=repo, pr_number=pr, prefetch_files=False)
    system = build_system_prompt([], ctx.diff_text, ctx.prompt_additions)
    user = _build_user_prompt(ctx, ctx.diff_text[:40_000])
    print("===== SYSTEM =====\n")
    print(system)
    print("\n===== USER =====\n")
    print(user[:40_000])


async def cmd_validate(findings_path: Path, files_path: Path | None) -> None:
    from app.agent.schema import Finding
    from app.agent.validator import FindingValidator

    payload = json.loads(findings_path.read_text(encoding="utf-8"))
    findings_raw = payload.get("findings") or payload.get("result", {}).get("findings") or []
    files = {}
    if files_path and files_path.exists():
        files = json.loads(files_path.read_text(encoding="utf-8"))
    validator = FindingValidator(files, commentable_lines=None)
    for idx, raw in enumerate(findings_raw):
        try:
            finding = Finding.model_validate(raw)
            ok, reason, detail = validator.validate(finding)
            print(f"[{idx}] {'ACCEPT' if ok else 'REJECT'} reason={reason} detail={detail}")
        except Exception as exc:
            print(f"[{idx}] REJECT reason=schema_error detail={exc}")


async def cmd_render(findings_path: Path) -> None:
    from app.agent.pipeline.delivery_sinks import DryRunDeliverySink
    from app.agent.schema import ReviewResult

    payload = json.loads(findings_path.read_text(encoding="utf-8"))
    if "result" in payload:
        result = ReviewResult.model_validate(payload["result"])
    else:
        result = ReviewResult.model_validate(payload)
    sink = DryRunDeliverySink()
    await sink.post(result, owner="o", repo="r", pr_number=1, commit_sha="deadbeef")
    print(sink.render_markdown())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Nash AI showcase entrypoints")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ctx = sub.add_parser("context", help="Dump PRContext JSON")
    p_ctx.add_argument("--owner", required=True)
    p_ctx.add_argument("--repo", required=True)
    p_ctx.add_argument("--pr", type=int, required=True)

    p_prompt = sub.add_parser("prompt", help="Render assembled prompts without LLM")
    p_prompt.add_argument("--owner", required=True)
    p_prompt.add_argument("--repo", required=True)
    p_prompt.add_argument("--pr", type=int, required=True)

    p_val = sub.add_parser("validate", help="Validate a findings batch")
    p_val.add_argument("--findings", type=Path, required=True)
    p_val.add_argument("--files", type=Path, default=None)

    p_render = sub.add_parser("render", help="Render GitHub comment bodies")
    p_render.add_argument("--findings", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.cmd == "context":
        asyncio.run(cmd_context(args.owner, args.repo, args.pr))
    elif args.cmd == "prompt":
        asyncio.run(cmd_prompt(args.owner, args.repo, args.pr))
    elif args.cmd == "validate":
        asyncio.run(cmd_validate(args.findings, args.files))
    elif args.cmd == "render":
        asyncio.run(cmd_render(args.findings))


if __name__ == "__main__":
    main()
