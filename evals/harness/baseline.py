"""Bare-model baseline — same model, same diff, one-paragraph prompt, no tools/validation."""

from __future__ import annotations

from typing import Any

from app.agent.finalize import finalize_review
from app.agent.review_config import DEFAULT_MODEL_NAME, DEFAULT_MODEL_PROVIDER
from app.agent.schema import PRContext, ReviewResult

BASELINE_SYSTEM = (
    "You are a senior code reviewer. Review the pull request diff and return actionable "
    "findings with file paths and line numbers. Prefer high-signal issues only."
)


async def run_bare_baseline(
    pr: PRContext,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    provider: str = DEFAULT_MODEL_PROVIDER,
) -> ReviewResult:
    user = (
        f"Repository: {pr.repo_full_name} PR #{pr.pr_number}\n"
        f"Title: {pr.title}\n\n"
        f"Diff:\n{pr.diff_text[:100_000]}\n"
    )
    context: dict[str, Any] = {
        "run_id": "baseline",
        "review_id": -1,
        "installation_id": 0,
        "owner": pr.owner,
        "repo": pr.repo,
        "pr_number": pr.pr_number,
        "head_sha": pr.head_sha,
        "input_tokens": 0,
        "output_tokens": 0,
        "tokens_used": 0,
        "fetched_files": dict(pr.files_at_head),
        "offline_tool_executor": _noop_tools(pr.files_at_head),
    }
    # No ReAct tools — jump straight to structured finalize with a single user message.
    messages = [{"role": "user", "content": user}]
    return await finalize_review(
        BASELINE_SYSTEM,
        messages,
        context,
        model_name=model_name,
        provider=provider,  # type: ignore[arg-type]
        allow_retry=False,
    )


def _noop_tools(files: dict[str, str]):
    async def _run(name: str, tool_input: dict[str, Any], context: dict[str, Any]) -> str:
        return f"Tool {name} disabled in bare baseline"

    return _run
