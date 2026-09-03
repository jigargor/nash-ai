"""Read/write docs/STATUS.json — the single source of truth for scores, rounds, spend."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_PATH = REPO_ROOT / "docs" / "STATUS.json"

MODULE_WAVE_ORDER: list[str] = [
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

PASS_SCORE = 8.5
MAX_ROUNDS_PER_MODULE = 4


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def load_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {"version": 1, "modules": {}, "budget": {"soft_cap_usd": 200, "remaining_usd": 200}}
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def save_status(status: dict[str, Any]) -> None:
    status["updated_at"] = now_iso()
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")


def record_module_round(
    module: str,
    *,
    score: float | None,
    passed: bool,
    open_issues: list[str],
    method: str,
    round_n: int,
    artifacts: list[str],
    evidence_llm_backed: bool,
) -> dict[str, Any]:
    status = load_status()
    modules = status.setdefault("modules", {})
    entry = modules.setdefault(
        module, {"score": None, "rounds": 0, "open_issues": [], "status": "not_scored"}
    )
    # `score` is reserved for LLM-backed critic verdicts over real model output. Offline/stub
    # evidence is recorded separately as `proxy_score` so nobody mistakes plumbing for quality.
    entry["score"] = score if evidence_llm_backed else None
    entry["proxy_score"] = score
    entry["rounds"] = max(int(entry.get("rounds") or 0), round_n)
    entry["open_issues"] = open_issues
    entry["method"] = method
    entry["artifacts"] = artifacts[-10:]
    entry["last_round_at"] = now_iso()
    entry["evidence_llm_backed"] = evidence_llm_backed
    if not evidence_llm_backed:
        entry["status"] = "smoke_only_blocked_no_llm_keys"
    elif passed:
        entry["status"] = "pass"
    else:
        entry["status"] = "fail"
    save_status(status)
    return status


def lowest_scoring_module(status: dict[str, Any]) -> str | None:
    """Lowest score first; unscored modules count as lowest; ties break by wave order."""
    modules = status.get("modules") or {}
    ranked: list[tuple[float, int, str]] = []
    for module in MODULE_WAVE_ORDER:
        entry = modules.get(module)
        if entry is None:
            continue
        if entry.get("status") == "pass":
            continue
        if int(entry.get("rounds") or 0) >= MAX_ROUNDS_PER_MODULE:
            continue
        score = entry.get("score")
        if score is None:
            score = entry.get("proxy_score")
        ranked.append((float(score) if score is not None else -1.0, MODULE_WAVE_ORDER.index(module), module))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def all_modules_pass(status: dict[str, Any]) -> bool:
    modules = status.get("modules") or {}
    return bool(modules) and all(entry.get("status") == "pass" for entry in modules.values())


def set_baseline(payload: dict[str, Any]) -> None:
    status = load_status()
    status["baseline"] = payload
    save_status(status)


def set_final_gate(payload: dict[str, Any]) -> None:
    status = load_status()
    status["final_gate"] = payload
    save_status(status)


def set_pairwise(payload: dict[str, Any]) -> None:
    status = load_status()
    status["pairwise"] = payload
    save_status(status)


def append_note(note: str) -> None:
    status = load_status()
    notes = status.setdefault("notes", [])
    if note not in notes:
        notes.append(note)
    save_status(status)
