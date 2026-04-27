"""Export a production review's context snapshot as an eval dataset directory.

The exported directory is compatible with run_eval.py:
  - diff.patch       ← the raw GitHub diff
  - context.json     ← repo, head_sha, fetched file contents
  - prompts/         ← system.txt + user.txt (for human debugging only)
  - snapshot.json    ← full decompressed snapshot (for tooling / full-fidelity replay)

Usage:
    python evals/export_snapshot.py --review-id 123 --out evals/datasets/my_case_001

The script connects to the database configured via DATABASE_URL.  Set it in
your environment or .env.local before running.

    DATABASE_URL=postgresql+asyncpg://... python evals/export_snapshot.py --review-id 123
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a review context snapshot to an eval dataset directory."
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
    return parser.parse_args()


async def _fetch_snapshot(review_id: int) -> dict:
    import dataclasses

    # Import here so the script fails fast with a clear message if sys.path is wrong.
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


def _write_dataset(out_dir: Path, data: dict, *, force: bool) -> None:
    if out_dir.exists() and not force:
        existing = list(out_dir.iterdir())
        if existing:
            print(
                f"Output directory {out_dir} already exists and is not empty.\n"
                "Use --force to overwrite.",
                file=sys.stderr,
            )
            sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)

    # diff.patch — consumed by run_eval.py harness
    diff_text = data.get("diff_text", "")
    if not diff_text:
        print("Warning: diff_text is empty or missing in snapshot.", file=sys.stderr)
    (out_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

    # context.json — consumed by run_eval.py harness
    pr = data.get("pr_metadata", {})
    context_json = {
        "repo": f"{pr.get('owner', '')}/{pr.get('repo', '')}",
        "head_sha": pr.get("head_sha", ""),
        "files": data.get("fetched_files", {}),
    }
    (out_dir / "context.json").write_text(
        json.dumps(context_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # prompts/ — human debugging only, not read by run_eval.py
    (prompts_dir / "system.txt").write_text(data.get("system_prompt", ""), encoding="utf-8")
    (prompts_dir / "user.txt").write_text(data.get("user_prompt", ""), encoding="utf-8")

    # snapshot.json — full fidelity, useful for tooling
    (out_dir / "snapshot.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Exported review {data.get('review_id')} to {out_dir}/")
    print(f"  diff.patch     {len(data.get('diff_text', ''))} chars")
    print(f"  context.json   {len(data.get('fetched_files', {}))} files")
    print(f"  snapshot.json  full payload")
    print()
    print("Next steps:")
    print(f"  1. Add evals/datasets/{out_dir.name}/expected.json with the expected findings.")
    print(f"  2. Run: python evals/run_eval.py --prompt-version candidate \\")
    print(f"          --predictions-dir evals/predictions/candidate")


def main() -> None:
    args = _parse_args()

    # Bootstrap Django-style: add apps/api/src to sys.path so app.* imports work.
    api_src = Path(__file__).parent.parent / "apps" / "api" / "src"
    if str(api_src) not in sys.path:
        sys.path.insert(0, str(api_src))

    # Load .env.local if present (DATABASE_URL etc.)
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
                pass  # dotenv not installed — user must set DATABASE_URL manually
            break

    data = asyncio.run(_fetch_snapshot(args.review_id))
    _write_dataset(args.out, data, force=args.force)


if __name__ == "__main__":
    main()
