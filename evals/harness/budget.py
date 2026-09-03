"""Eval spend guard — write budget before spending; abort when exceeded."""

from __future__ import annotations

from typing import Any

from evals.harness.status import load_status, save_status

# Conservative per-PR uncached spend projection (Sonnet 5, S/M PR) used before any call.
PROJECTED_USD_PER_PR = 0.50


def allocate_round_budget(amount_usd: float, *, round_id: int | None = None) -> dict[str, Any]:
    status = load_status()
    budget = status.setdefault("budget", {})
    remaining = float(budget.get("remaining_usd", budget.get("soft_cap_usd", 200)))
    if amount_usd > remaining:
        raise RuntimeError(
            f"Round budget ${amount_usd} exceeds remaining ${remaining}. Refuse to spend."
        )
    budget["round_allocated_usd"] = amount_usd
    budget["round_spent_usd"] = 0.0
    if round_id is not None:
        status["current_round"] = round_id
        budget[f"round_{round_id}_allocated_usd"] = amount_usd
    save_status(status)
    return status


def record_spend(amount_usd: float) -> dict[str, Any]:
    status = load_status()
    budget = status.setdefault("budget", {})
    spent = float(budget.get("total_spent_usd", 0)) + amount_usd
    soft_cap = float(budget.get("soft_cap_usd", 200))
    budget["total_spent_usd"] = round(spent, 4)
    budget["remaining_usd"] = round(soft_cap - spent, 4)
    budget["last_spend_usd"] = round(amount_usd, 4)
    budget["round_spent_usd"] = round(float(budget.get("round_spent_usd", 0.0)) + amount_usd, 4)
    round_id = status.get("current_round")
    if round_id is not None:
        key = f"round_{round_id}_spent_usd"
        budget[key] = round(float(budget.get(key, 0.0)) + amount_usd, 4)
    save_status(status)
    if spent > soft_cap:
        raise RuntimeError(f"Eval soft cap ${soft_cap} exceeded (spent ${spent}).")
    return status


def estimate_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    input_per_1m: float = 2.0,
    output_per_1m: float = 10.0,
) -> float:
    return (input_tokens / 1_000_000) * input_per_1m + (output_tokens / 1_000_000) * output_per_1m


def check_projected_spend(projected_usd: float) -> None:
    status = load_status()
    budget = status.get("budget") or {}
    remaining = float(budget.get("remaining_usd", budget.get("soft_cap_usd", 200)))
    round_allocated = float(budget.get("round_allocated_usd", remaining))
    round_spent = float(budget.get("round_spent_usd", 0.0))
    round_remaining = round_allocated - round_spent
    if projected_usd > min(remaining, round_remaining):
        raise RuntimeError(
            f"Projected uncached spend ${projected_usd:.4f} exceeds remaining "
            f"(round ${round_remaining:.4f}, total ${remaining:.4f}); refusing to run."
        )
