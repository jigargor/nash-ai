"""Generate prediction files for eval harness from offline snapshot replay.

Modes
-----
snapshot (default)
    Deterministic, no LLM keys required.  Reads ``snapshot.json`` from each
    dataset directory, finds the last ``submit_review`` tool-use call in the
    stored agent messages, and writes its arguments as the prediction file.

live
    Actually calls the LLM with the snapshot's context (requires API keys).
    Intended for local development and new-dataset bootstrapping only.

dry-run flag
    Validates that all cases have the necessary input files without writing
    any prediction files.  Exits non-zero if any case is missing required
    files for the requested mode.

Stale-detection
---------------
Each prediction file carries a ``code_hash`` field computed from:
  - The current ``PROMPT_VERSION`` constant
  - The contents of every prompt file under ``apps/api/src/app/agent/prompts/``
  - The prediction-generation mode and prompt-version label

When the same case is generated again, the new ``code_hash`` is compared with
the stored one.  A mismatch means the prompts or version label changed since
the last generation.  CI can fail on staleness by checking this field against
a freshly computed hash.

Usage
-----
    python evals/generate_predictions.py \\
        --prompt-version v4-reviewer-editor \\
        --mode snapshot \\
        --datasets-dir evals/datasets \\
        --output-dir evals/predictions/candidate \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EVALS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _EVALS_DIR.parent
_PROMPTS_DIR = _REPO_ROOT / "apps" / "api" / "src" / "app" / "agent" / "prompts"
_CONSTANTS_FILE = _REPO_ROOT / "apps" / "api" / "src" / "app" / "agent" / "constants.py"


# ---------------------------------------------------------------------------
# Stale-detection helpers
# ---------------------------------------------------------------------------


def _read_prompt_version_from_constants() -> str:
    """Extract PROMPT_VERSION from constants.py without importing the module."""
    if not _CONSTANTS_FILE.exists():
        return "unknown"
    for line in _CONSTANTS_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("PROMPT_VERSION"):
            # e.g.  PROMPT_VERSION = "v4-reviewer-editor"
            parts = stripped.split("=", 1)
            if len(parts) == 2:
                return parts[1].strip().strip('"').strip("'")
    return "unknown"


def compute_code_hash(prompt_version: str) -> str:
    """Return a SHA-256 hex digest that covers prompt content + version label.

    The hash is computed over:
    - ``prompt_version`` (the CLI label passed to --prompt-version)
    - The ``PROMPT_VERSION`` constant from constants.py
    - The full contents of every file inside the prompts directory (sorted by
      relative path for determinism)

    Changing any prompt file or bumping ``PROMPT_VERSION`` will invalidate
    previously generated predictions.
    """
    h = hashlib.sha256()
    h.update(prompt_version.encode())

    # Include the source-of-truth constant so version-label drift is caught.
    h.update(_read_prompt_version_from_constants().encode())

    if _PROMPTS_DIR.exists():
        for prompt_file in sorted(_PROMPTS_DIR.rglob("*")):
            if prompt_file.is_file():
                h.update(prompt_file.relative_to(_PROMPTS_DIR).as_posix().encode())
                h.update(prompt_file.read_bytes())

    return h.hexdigest()


# ---------------------------------------------------------------------------
# Snapshot-mode extraction
# ---------------------------------------------------------------------------


def _extract_submit_review_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return the findings list from the last ``submit_review`` tool call.

    The snapshot format produced by ``export_snapshot.py`` stores the full
    agent message history under the ``messages`` key (a list of Anthropic
    content blocks serialised as dicts).  We scan backwards for the last
    assistant turn that contains a ``tool_use`` block whose ``name`` is
    ``submit_review``.

    Returns ``None`` when no such call is found (e.g. the snapshot predates
    the submit_review tool or the agent timed out).
    """
    messages = snapshot.get("messages", [])
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        if role != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in reversed(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "submit_review":
                tool_input = block.get("input", {})
                if isinstance(tool_input, dict):
                    findings = tool_input.get("findings", [])
                    if isinstance(findings, list):
                        return findings  # type: ignore[return-value]
    return None


def _model_from_snapshot(snapshot: dict[str, Any]) -> str:
    """Best-effort extraction of the model name from a snapshot."""
    return str(snapshot.get("model", "unknown"))


# ---------------------------------------------------------------------------
# Per-case generation
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[return-value]


def _validate_case_snapshot_mode(case_dir: Path) -> list[str]:
    """Return a list of validation errors for snapshot mode."""
    errors: list[str] = []
    snapshot_path = case_dir / "snapshot.json"
    context_path = case_dir / "context.json"
    expected_path = case_dir / "expected.json"

    if not expected_path.exists():
        errors.append(f"  missing expected.json")
    if not snapshot_path.exists() and not context_path.exists():
        errors.append(f"  missing both snapshot.json and context.json (need at least one)")
    return errors


def _validate_case_live_mode(case_dir: Path) -> list[str]:
    """Return a list of validation errors for live mode."""
    errors: list[str] = []
    expected_path = case_dir / "expected.json"
    context_path = case_dir / "context.json"

    if not expected_path.exists():
        errors.append(f"  missing expected.json")
    if not context_path.exists():
        errors.append(f"  missing context.json (required for live mode)")
    return errors


def generate_snapshot_prediction(
    case_dir: Path,
    prompt_version: str,
    code_hash: str,
) -> dict[str, Any] | None:
    """Generate a prediction dict from snapshot replay.

    Returns ``None`` when the case should be skipped (with a warning emitted).
    """
    snapshot_path = case_dir / "snapshot.json"

    if snapshot_path.exists():
        snapshot = _load_json(snapshot_path)
        findings = _extract_submit_review_from_snapshot(snapshot)
        model = _model_from_snapshot(snapshot)
        if findings is None:
            print(
                f"  [WARN] {case_dir.name}: no submit_review call found in snapshot — "
                "falling back to empty findings list",
                file=sys.stderr,
            )
            findings = []
    else:
        # No snapshot — nothing to replay deterministically.
        print(
            f"  [WARN] {case_dir.name}: no snapshot.json found; skipping (run with "
            "--mode=live to generate predictions from scratch)",
            file=sys.stderr,
        )
        return None

    return {
        "findings": findings,
        "prompt_version": prompt_version,
        "model": model,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "code_hash": code_hash,
        "mode": "snapshot",
    }


def generate_live_prediction(
    case_dir: Path,
    prompt_version: str,
    code_hash: str,
) -> dict[str, Any] | None:
    """Generate a prediction dict by calling the LLM with the case context.

    This path is for local development only.  It requires API keys and the
    full ``app`` package on ``sys.path``.

    Returns ``None`` on failure (with error printed to stderr).
    """
    # Add apps/api/src to sys.path so ``app.*`` imports resolve.
    api_src = _REPO_ROOT / "apps" / "api" / "src"
    if str(api_src) not in sys.path:
        sys.path.insert(0, str(api_src))

    # Lazy import — fail with a clear message if the package isn't importable.
    try:
        import asyncio

        from app.agent.runner import run_review  # type: ignore[import-untyped]
    except ImportError as exc:
        print(
            f"  [ERROR] {case_dir.name}: cannot import app.agent.runner — {exc}\n"
            "  Ensure you are running from apps/api/ with `uv run python ...` or "
            "that the package is on sys.path.",
            file=sys.stderr,
        )
        return None

    context = _load_json(case_dir / "context.json")
    diff_path = case_dir / "diff.patch"
    diff_text = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""

    try:
        result = asyncio.run(
            run_review(
                diff_text=diff_text,
                context=context,
                prompt_version=prompt_version,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERROR] {case_dir.name}: live review failed — {exc}", file=sys.stderr)
        return None

    findings = result.get("findings", []) if isinstance(result, dict) else []
    model = result.get("model", "unknown") if isinstance(result, dict) else "unknown"

    return {
        "findings": findings,
        "prompt_version": prompt_version,
        "model": model,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "code_hash": code_hash,
        "mode": "live",
    }


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------


def check_staleness(predictions_dir: Path, current_hash: str) -> list[str]:
    """Return a list of case IDs whose stored predictions are stale.

    A prediction is considered stale when it carries a ``code_hash`` that
    differs from *current_hash* (i.e. the prompts or version label changed
    since the prediction was generated).
    """
    stale: list[str] = []
    if not predictions_dir.exists():
        return stale
    for pred_file in sorted(predictions_dir.glob("*.json")):
        try:
            payload = _load_json(pred_file)
        except Exception:  # noqa: BLE001
            stale.append(pred_file.stem + " (unreadable)")
            continue
        stored_hash = payload.get("code_hash", "")
        if stored_hash != current_hash:
            stale.append(pred_file.stem)
    return stale


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def run(
    prompt_version: str,
    mode: str,
    datasets_dir: Path,
    output_dir: Path,
    dry_run: bool,
) -> int:
    """Run prediction generation.  Returns 0 on success, non-zero on error."""
    code_hash = compute_code_hash(prompt_version)
    print(f"Code hash: {code_hash[:16]}…  (prompt_version={prompt_version!r}, mode={mode!r})")

    if not datasets_dir.exists():
        print(f"ERROR: datasets directory not found: {datasets_dir}", file=sys.stderr)
        return 1

    case_dirs = sorted(p for p in datasets_dir.iterdir() if p.is_dir())
    if not case_dirs:
        print(f"ERROR: no case directories found under {datasets_dir}", file=sys.stderr)
        return 1

    print(f"Found {len(case_dirs)} case(s): {', '.join(d.name for d in case_dirs)}")

    # ---- Validation pass (always run) ------------------------------------
    all_valid = True
    for case_dir in case_dirs:
        if mode == "snapshot":
            errors = _validate_case_snapshot_mode(case_dir)
        else:
            errors = _validate_case_live_mode(case_dir)
        if errors:
            print(f"  [INVALID] {case_dir.name}:", file=sys.stderr)
            for err in errors:
                print(err, file=sys.stderr)
            all_valid = False

    if not all_valid:
        print(
            "\nValidation failed — fix the above errors before generating predictions.",
            file=sys.stderr,
        )
        return 2

    print("Input validation passed.")

    if dry_run:
        print("--dry-run: skipping prediction generation.")
        return 0

    # ---- Staleness report on existing predictions ------------------------
    stale = check_staleness(output_dir, code_hash)
    if stale:
        print(
            f"\n[STALE] The following existing predictions have an outdated code_hash "
            f"and will be overwritten:\n  " + "\n  ".join(stale)
        )

    # ---- Generation pass -------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = 0
    skipped = 0

    for case_dir in case_dirs:
        print(f"\nProcessing {case_dir.name} …")
        if mode == "snapshot":
            prediction = generate_snapshot_prediction(case_dir, prompt_version, code_hash)
        else:
            prediction = generate_live_prediction(case_dir, prompt_version, code_hash)

        if prediction is None:
            skipped += 1
            continue

        out_path = output_dir / f"{case_dir.name}.json"
        out_path.write_text(json.dumps(prediction, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {out_path.relative_to(Path.cwd())} ({len(prediction['findings'])} finding(s))")
        generated += 1

    print(f"\nDone. generated={generated} skipped={skipped} output_dir={output_dir}")

    if skipped > 0 and mode == "snapshot":
        print(
            "\nTip: some cases were skipped because they lack snapshot.json.  "
            "Run `evals/export_snapshot.py` to capture live review snapshots, "
            "or use --mode=live to generate predictions directly.",
            file=sys.stderr,
        )

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate eval predictions from offline snapshot replay or live LLM calls.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--prompt-version",
        required=True,
        help="Prompt version label (stamped into every prediction file).",
    )
    parser.add_argument(
        "--mode",
        choices=["snapshot", "live"],
        default="snapshot",
        help="Generation mode: 'snapshot' (offline, no API keys) or 'live' (calls LLM).",
    )
    parser.add_argument(
        "--datasets-dir",
        default="evals/datasets",
        help="Root directory containing eval case subdirectories.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for prediction files.  Defaults to evals/predictions/<prompt-version>/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs only; do not write any prediction files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    datasets_dir = Path(args.datasets_dir)
    output_dir = Path(args.output_dir or f"evals/predictions/{args.prompt_version}")
    sys.exit(
        run(
            prompt_version=args.prompt_version,
            mode=args.mode,
            datasets_dir=datasets_dir,
            output_dir=output_dir,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
