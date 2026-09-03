"""Export Pydantic Finding/ReviewStatus/DropReason JSON schema for shared-types drift checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

API_SRC = Path(__file__).resolve().parents[1] / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from app.agent.schema import DropReason, Finding, ReviewResult  # noqa: E402
from app.observability.events import TerminalStatus  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "packages" / "shared-types" / "generated" / "pydantic-schema.json"

REVIEW_STATUSES = [
    "queued",
    "running",
    "done",
    "failed",
    "skipped",
    "canceled",
    "partial",
    "rate_limited",
    "budget_exhausted",
]


def build_schema() -> dict[str, object]:
    drop_reasons = list(DropReason.__args__)  # type: ignore[attr-defined]
    return {
        "finding": Finding.model_json_schema(),
        "review_result": ReviewResult.model_json_schema(),
        "drop_reasons": drop_reasons,
        "review_statuses": REVIEW_STATUSES,
        "terminal_statuses": list(TerminalStatus.__args__),  # type: ignore[attr-defined]
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = build_schema()
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
