"""Critic / judge helpers for module gauntlets (scores from harness artifacts only).

Two critics exist:

* ``score_from_metrics`` — deterministic proxy over ``metrics.json``. Always available,
  never LLM-backed; labelled ``metrics_proxy_critic``.
* ``llm_critic`` — fresh-context Opus 5 critic that reads only the run directory plus the
  rubric. Requires an Anthropic key; when missing it returns ``None`` and callers must
  record the module as unscored-by-LLM rather than inventing a number.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

WEIGHTS = {
    "anchoring": 25,
    "suggestion_validity": 20,
    "severity_calibration": 15,
    "groundedness": 20,
    "noise_fp": 15,
}
PASS_SCORE = 8.5
PIPELINE_ERROR_CAP = 7.0

RUBRIC = """
Score the review run on five dimensions (0-10 each):
- anchoring (25%): every finding points at the exact changed line it discusses.
- suggestion_validity (20%): suggestion blocks apply cleanly, parse, and are non-noop fixes.
- severity_calibration (15%): severities match the real blast radius (no inflated nits).
- groundedness (20%): claims are supported by the diff/tool trace; no invented APIs.
- noise_fp (15%): no false positives, duplicates, or style-only chatter ahead of risk.
Any pipeline error caps the total at 7.0. Output JSON only:
{"dimensions": {...}, "issues": ["ranked, concrete, evidence-cited"], "verdict": "..."}
""".strip()


def score_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Deterministic proxy critic from harness metrics (no LLM)."""
    pipeline_errors = int(metrics.get("pipeline_errors") or 0)
    anchoring = metrics.get("anchoring") or {}
    suggestions = metrics.get("suggestions") or {}
    groundedness = metrics.get("groundedness") or {}
    golden = metrics.get("golden") or {}
    finding_count = int(metrics.get("finding_count") or 0)

    # Anchoring: only score when there is something to anchor; no findings => unscored (not 10).
    anchoring_score = (
        float(anchoring.get("exact_rate") or 0.0) * 10 if finding_count else None
    )
    suggestion_total = int(suggestions.get("with_suggestion") or 0)
    suggestion_score = (
        float(suggestions.get("apply_rate") or 0.0) * 10 if suggestion_total else None
    )
    groundedness_score = (
        float(groundedness.get("groundedness_proxy") or 0.0) * 10 if finding_count else None
    )
    if golden:
        severity_score = float(golden.get("severity_calibration") or golden.get("precision") or 0) * 10
        noise_score = max(0.0, 10.0 - float(golden.get("fp") or 0) * 2.0)
        if golden.get("clean_case") and not golden.get("clean_with_fp"):
            noise_score = 10.0
    else:
        severity_score = None
        noise_score = None

    dims: dict[str, float | None] = {
        "anchoring": anchoring_score,
        "suggestion_validity": suggestion_score,
        "severity_calibration": severity_score,
        "groundedness": groundedness_score,
        "noise_fp": noise_score,
    }
    scored = {k: v for k, v in dims.items() if v is not None}
    if scored:
        weight_total = sum(WEIGHTS[k] for k in scored)
        weighted: float | None = sum(scored[k] * WEIGHTS[k] for k in scored) / weight_total
    else:
        weighted = None
    if weighted is not None and pipeline_errors > 0:
        weighted = min(weighted, PIPELINE_ERROR_CAP)

    issues: list[str] = []
    if pipeline_errors:
        issues.append(f"pipeline_errors={pipeline_errors}: {metrics.get('pipeline_error_messages')}")
    if anchoring_score is not None and anchoring_score < PASS_SCORE:
        issues.append(f"anchoring.exact_rate={anchoring.get('exact_rate')} below 0.85")
    if suggestion_score is not None and suggestion_score < PASS_SCORE:
        issues.append(f"suggestion.apply_rate={suggestions.get('apply_rate')} below 0.85")
    if groundedness_score is not None and groundedness_score < PASS_SCORE:
        issues.append("groundedness_proxy below 0.85")
    if golden and golden.get("fn"):
        issues.append(f"golden misses (fn)={golden.get('fn')}")
    if golden and golden.get("fp"):
        issues.append(f"golden false positives (fp)={golden.get('fp')}")
    return {
        "score": round(weighted, 2) if weighted is not None else None,
        "dimensions": {k: (round(v, 2) if v is not None else None) for k, v in dims.items()},
        "scored_dimensions": sorted(scored),
        "pass": bool(weighted is not None and weighted >= PASS_SCORE and pipeline_errors == 0),
        "open_issues": issues,
        "method": "metrics_proxy_critic",
        "llm_backed": False,
    }


def aggregate_critic(per_run: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean +/- sd over runs; unscored runs are excluded from the mean and reported."""
    scores = [float(r["score"]) for r in per_run if r.get("score") is not None]
    issues: list[str] = []
    for r in per_run:
        for issue in r.get("open_issues") or []:
            if issue not in issues:
                issues.append(issue)
    mean = round(statistics.fmean(scores), 2) if scores else None
    sd = round(statistics.pstdev(scores), 2) if len(scores) > 1 else 0.0
    errors = sum(1 for r in per_run if any("pipeline_errors=" in i for i in (r.get("open_issues") or [])))
    return {
        "score": mean,
        "score_sd": sd,
        "runs": len(per_run),
        "scored_runs": len(scores),
        "unscored_runs": len(per_run) - len(scores),
        "pipeline_error_runs": errors,
        "pass": bool(mean is not None and mean >= PASS_SCORE and errors == 0),
        "open_issues": issues[:20],
        "method": per_run[0].get("method") if per_run else "none",
        "llm_backed": all(bool(r.get("llm_backed")) for r in per_run) if per_run else False,
    }


def write_critic_result(module: str, round_n: int, payload: dict[str, Any], root: Path) -> Path:
    out_dir = root / "evals" / "critic" / module
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"round-{round_n}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _read_run_dir(run_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"run_dir": str(run_dir)}
    for name in ("metrics.json", "findings.json", "meta.json", "golden_diff.json"):
        path = run_dir / name
        if path.exists():
            try:
                payload[name.removesuffix(".json")] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload[name.removesuffix(".json")] = None
    rendered = run_dir / "rendered_comments.md"
    payload["rendered_comments"] = rendered.read_text(encoding="utf-8") if rendered.exists() else ""
    return payload


async def llm_critic(run_dir: Path, *, module: str, model_name: str = "claude-opus-5") -> dict[str, Any] | None:
    """Fresh-context LLM critic over one run directory. Returns None without an API key."""
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from app.config import settings

            if not settings.anthropic_api_key:
                return None
        except Exception:
            return None
    from app.llm.providers import StructuredOutputRequest, get_provider_adapter

    payload = _read_run_dir(run_dir)
    findings = (payload.get("findings") or {}).get("result", {})
    critic_input = {
        "module_under_review": module,
        "metrics": payload.get("metrics"),
        "findings": findings,
        "drops": (payload.get("findings") or {}).get("drops"),
        "rendered_comments": payload.get("rendered_comments", "")[:30_000],
        "golden_diff": payload.get("golden_diff"),
    }
    schema = {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "object",
                "properties": {k: {"type": "number"} for k in WEIGHTS},
                "required": list(WEIGHTS),
            },
            "issues": {"type": "array", "items": {"type": "string"}},
            "verdict": {"type": "string"},
        },
        "required": ["dimensions", "issues", "verdict"],
    }
    adapter = get_provider_adapter("anthropic")
    context: dict[str, Any] = {"llm_effort": "high", "model_role": "critic"}
    try:
        structured = await adapter.structured_output(
            request=StructuredOutputRequest(
                model_name=model_name,
                system_prompt=(
                    "You are a fresh-context critic scoring a code-review pipeline run. You see "
                    "only harness artifacts. Never award points for output you cannot verify in "
                    "the artifacts.\n\n" + RUBRIC
                ),
                messages=[{"role": "user", "content": json.dumps(critic_input, default=str)[:180_000]}],
                tool_name="submit_critic_verdict",
                tool_description="Submit dimension scores and ranked issues.",
                input_schema=schema,
                context=context,
                max_tokens=4096,
                effort="high",
            )
        )
    except Exception as exc:
        return {"score": None, "method": "llm_critic_failed", "error": str(exc), "llm_backed": False}
    dims = {k: float(v) for k, v in (structured.payload.get("dimensions") or {}).items() if k in WEIGHTS}
    weighted = sum(dims.get(k, 0.0) * (WEIGHTS[k] / 100.0) for k in WEIGHTS)
    metrics = payload.get("metrics") or {}
    if int(metrics.get("pipeline_errors") or 0) > 0:
        weighted = min(weighted, PIPELINE_ERROR_CAP)
    return {
        "score": round(weighted, 2),
        "dimensions": dims,
        "pass": weighted >= PASS_SCORE and int(metrics.get("pipeline_errors") or 0) == 0,
        "open_issues": list(structured.payload.get("issues") or [])[:20],
        "verdict": structured.payload.get("verdict"),
        "method": f"llm_critic:{model_name}",
        "llm_backed": True,
        "tokens_used": int(context.get("tokens_used") or 0),
        "cost_usd": float(context.get("cost_usd") or 0.0),
    }
