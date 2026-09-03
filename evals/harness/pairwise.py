"""Blind pairwise judge — A/B shuffled comparison of two reviews."""

from __future__ import annotations

import json
import random
from typing import Any

from app.agent.finalize import finalize_review
from app.agent.schema import ReviewResult

JUDGE_SYSTEM = (
    "You are judging which of two code reviews is better for the same pull request. "
    "Prefer reviews that are correctly anchored, actionable, well-calibrated on severity, "
    "grounded in the diff, and free of hallucinated API/vendor claims. "
    "Put your verdict in the summary as JSON: "
    '{"winner":"A"|"B"|"tie","reason":"..."}.'
)


async def _disabled(name: str, tool_input: dict[str, Any], context: dict[str, Any]) -> str:
    return f"Tool {name} disabled in pairwise judge"


async def blind_pairwise(
    *,
    diff_text: str,
    review_a: ReviewResult,
    review_b: ReviewResult,
    judge_model: str = "claude-opus-5",
    judge_provider: str = "anthropic",
    seed: int = 0,
) -> dict[str, Any]:
    rng = random.Random(seed)
    order = ["A", "B"]
    rng.shuffle(order)
    mapping = {"A": review_a, "B": review_b}
    first_key, second_key = order[0], order[1]
    first = mapping[first_key]
    second = mapping[second_key]
    prompt = (
        "Diff (truncated):\n"
        f"{diff_text[:40_000]}\n\n"
        f"Review A:\n{json.dumps(first.model_dump(mode='json'), indent=2)}\n\n"
        f"Review B:\n{json.dumps(second.model_dump(mode='json'), indent=2)}\n"
    )
    context: dict[str, Any] = {
        "run_id": "pairwise",
        "review_id": -1,
        "installation_id": 0,
        "owner": "eval",
        "repo": "eval",
        "pr_number": 1,
        "head_sha": "pairwise",
        "input_tokens": 0,
        "output_tokens": 0,
        "tokens_used": 0,
        "fetched_files": {},
        "offline_tool_executor": _disabled,
    }
    try:
        judged = await finalize_review(
            JUDGE_SYSTEM,
            [{"role": "user", "content": prompt}],
            context,
            model_name=judge_model,
            provider=judge_provider,  # type: ignore[arg-type]
            allow_retry=False,
        )
        raw = judged.summary
        winner_label = "tie"
        reason = raw
        try:
            blob = raw
            if judged.findings:
                blob = judged.findings[0].message
            start = blob.find("{")
            end = blob.rfind("}") + 1
            parsed = json.loads(blob[start:end])
            winner_label = str(parsed.get("winner") or "tie").upper()
            reason = str(parsed.get("reason") or reason)
        except Exception:
            lowered = raw.lower()
            if "winner" in lowered and '"a"' in lowered:
                winner_label = "A"
            elif "winner" in lowered and '"b"' in lowered:
                winner_label = "B"
        true_winner = "tie"
        if winner_label == "A":
            true_winner = first_key
        elif winner_label == "B":
            true_winner = second_key
        return {
            "winner": true_winner,
            "presented_order": [first_key, second_key],
            "raw_winner_label": winner_label,
            "reason": reason,
            "tokens_used": int(context.get("tokens_used") or 0),
        }
    except Exception as exc:
        return {
            "winner": "error",
            "presented_order": [first_key, second_key],
            "reason": str(exc),
            "tokens_used": int(context.get("tokens_used") or 0),
        }


def wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    phat = wins / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * ((phat * (1 - phat) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (centre - margin) / denom)
