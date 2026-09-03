"""Export a production review's context snapshot as a harness dataset case.

The exported directory is consumed directly by ``evals/harness/run.py --local-only``:
  - diff.patch       <- the raw GitHub diff
  - context.json     <- repo, pr_number, head_sha, title, body, fetched file contents
  - expected.json    <- goldens derived from human labels (finding_labels) and missed_issues
  - prompts/         <- system.txt + user.txt (for human debugging only)
  - snapshot.json    <- full decompressed snapshot (for tooling / full-fidelity replay)

Usage:
    python evals/export_snapshot.py --review-id 123 --out evals/datasets/prod_123
    python evals/export_snapshot.py --review-id 123 --out evals/datasets/prod_123 --without-labels

Golden derivation (``expected.json``):
  * findings labelled true_positive / accepted / accepted_with_modification / severity_wrong /
    category_wrong are kept as expected findings (the label decides what "correct" means);
  * findings labelled false_positive / duplicate / not_actionable / correct_but_too_minor are
    written to ``expected.json["negatives"]`` so the harness can count them as clean-FP checks;
  * every missed_issues row becomes an expected finding (recall golden).

The script connects to the database configured via DATABASE_URL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

POSITIVE_LABELS = {
    "true_positive",
    "accepted",
    "accepted_with_modification",
    "severity_wrong",
    "category_wrong",
}
NEGATIVE_LABELS = {"false_positive", "duplicate", "not_actionable", "correct_but_too_minor"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a review context snapshot to a harness dataset directory."
    )
    parser.add_argument("--review-id", type=int, required=True, help="Review ID to export.")
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory path (created if it does not exist).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files if the output directory already exists.",
    )
    parser.add_argument(
        "--without-labels",
        action="store_true",
        help="Skip finding_labels/missed_issues and write an empty expected.json.",
    )
    return parser.parse_args()


async def _fetch_snapshot(review_id: int) -> dict[str, Any]:
    import dataclasses

    try:
        from app.agent.snapshot import load_snapshot
    except ImportError as exc:
        print(
            f"Import error: {exc}\n"
            "Run from the repo root with the api package on sys.path:\n"
            "  cd apps/api && uv run python ../../evals/export_snapshot.py --review-id ...",
            file=sys.stderr,
        )
        sys.exit(1)

    snapshot = await load_snapshot(review_id)
    if snapshot is None:
        print(
            f"No snapshot found for review {review_id}.\n"
            "Snapshots are only captured for non-chunked reviews that reach the context-assembly stage.",
            file=sys.stderr,
        )
        sys.exit(1)

    return dataclasses.asdict(snapshot)


async def _fetch_goldens(review_id: int) -> dict[str, Any]:
    """Derive expected.json from human labels and missed issues for this review."""
    from sqlalchemy import select

    from app.db.models import FindingLabel, MissedIssue, Review
    from app.db.session import AsyncSessionLocal, set_installation_context

    async with AsyncSessionLocal() as session:
        review = await session.get(Review, review_id)
        if review is None:
            return {"findings": [], "negatives": [], "source": "review_not_found"}
        await set_installation_context(session, int(review.installation_id))
        findings_payload = review.findings if isinstance(review.findings, dict) else {}
        posted = findings_payload.get("findings") or []
        labels = list(
            await session.scalars(select(FindingLabel).where(FindingLabel.review_id == review_id))
        )
        missed = list(
            await session.scalars(select(MissedIssue).where(MissedIssue.review_id == review_id))
        )

    expected: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    for label in labels:
        index = int(label.finding_index)
        if not (0 <= index < len(posted)) or not isinstance(posted[index], dict):
            continue
        finding = posted[index]
        entry = {
            "file_path": finding.get("file_path"),
            "line_start": finding.get("line_start"),
            "category": finding.get("category"),
            "severity": finding.get("severity"),
            "message": finding.get("message"),
            "label": label.label,
            "notes": label.notes,
        }
        if label.label in POSITIVE_LABELS:
            expected.append(entry)
        elif label.label in NEGATIVE_LABELS:
            negatives.append(entry)
    for issue in missed:
        expected.append(
            {
                "file_path": issue.file_path,
                "line_start": int(issue.line_start),
                "line_end": int(issue.line_end) if issue.line_end is not None else None,
                "category": issue.expected_category,
                "severity": issue.expected_severity,
                "message": issue.description,
                "label": "missed_issue",
                "how_found": issue.how_found,
            }
        )
    return {
        "findings": expected,
        "negatives": negatives,
        "source": "finding_labels+missed_issues",
        "labelled_findings": len(labels),
        "missed_issues": len(missed),
        "posted_findings": len(posted),
    }


def _write_dataset(out_dir: Path, data: dict[str, Any], goldens: dict[str, Any], *, force: bool) -> None:
    if out_dir.exists() and not force:
        existing = list(out_dir.iterdir())
        if existing:
            print(
                f"Output directory {out_dir} already exists and is not empty.\nUse --force to overwrite.",
                file=sys.stderr,
            )
            sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)

    diff_text = data.get("diff_text", "")
    if not diff_text:
        print("Warning: diff_text is empty or missing in snapshot.", file=sys.stderr)
    (out_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

    pr = data.get("pr_metadata", {})
    context_json = {
        "repo": f"{pr.get('owner', '')}/{pr.get('repo', '')}",
        "pr_number": pr.get("pr_number", 1),
        "head_sha": pr.get("head_sha", ""),
        "title": pr.get("title", ""),
        "body": pr.get("body", ""),
        "files": data.get("fetched_files", {}),
        "review_id": data.get("review_id"),
    }
    (out_dir / "context.json").write_text(
        json.dumps(context_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "expected.json").write_text(
        json.dumps(goldens, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    (prompts_dir / "system.txt").write_text(data.get("system_prompt", ""), encoding="utf-8")
    (prompts_dir / "user.txt").write_text(data.get("user_prompt", ""), encoding="utf-8")
    (out_dir / "snapshot.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Exported review {data.get('review_id')} to {out_dir}/")
    print(f"  diff.patch     {len(diff_text)} chars")
    print(f"  context.json   {len(data.get('fetched_files', {}))} files")
    print(
        f"  expected.json  {len(goldens.get('findings', []))} expected, "
        f"{len(goldens.get('negatives', []))} negatives ({goldens.get('source')})"
    )
    print()
    print("Next steps:")
    if not goldens.get("findings"):
        print("  1. Label findings in the dashboard (or report missed issues), then re-export.")
    print(f"  2. Run: python evals/harness/run.py --local-only --datasets-dir {out_dir.parent}")


def main() -> None:
    args = _parse_args()

    api_src = Path(__file__).parent.parent / "apps" / "api" / "src"
    if str(api_src) not in sys.path:
        sys.path.insert(0, str(api_src))

    env_files = [
        Path(__file__).parent.parent / ".env.local",
        Path(__file__).parent.parent / "apps" / "api" / ".env.local",
    ]
    for env_file in env_files:
        if env_file.exists():
            try:
                from dotenv import load_dotenv  # type: ignore[import-untyped]

                load_dotenv(env_file, override=False)
            except ImportError:
                pass
            break

    data = asyncio.run(_fetch_snapshot(args.review_id))
    goldens: dict[str, Any]
    if args.without_labels:
        goldens = {"findings": [], "negatives": [], "source": "labels_skipped"}
    else:
        goldens = asyncio.run(_fetch_goldens(args.review_id))
    _write_dataset(args.out, data, goldens, force=args.force)


if __name__ == "__main__":
    main()
