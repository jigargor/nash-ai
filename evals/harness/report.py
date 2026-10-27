"""Write per-run harness artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "evals" / "runs"


def new_run_dir(label: str | None = None) -> Path:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}_{label or uuid4().hex[:8]}"
    path = RUNS_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_run_artifacts(
    run_dir: Path,
    *,
    findings: dict[str, Any],
    metrics: dict[str, Any],
    rendered_comments: str,
    trace_events: list[dict[str, Any]] | None = None,
    golden_diff: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "findings.json").write_text(
        json.dumps(findings, indent=2, default=str), encoding="utf-8"
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8"
    )
    (run_dir / "rendered_comments.md").write_text(rendered_comments, encoding="utf-8")
    if trace_events is not None:
        with (run_dir / "trace.jsonl").open("w", encoding="utf-8") as handle:
            for event in trace_events:
                handle.write(json.dumps(event, default=str) + "\n")
    if golden_diff is not None:
        (run_dir / "golden_diff.json").write_text(
            json.dumps(golden_diff, indent=2, default=str), encoding="utf-8"
        )
    if meta is not None:
        (run_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, default=str), encoding="utf-8"
        )
