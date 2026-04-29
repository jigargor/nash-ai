from __future__ import annotations

from collections import Counter
from fnmatch import fnmatch
from typing import Any


def compact_fast_path_prompt_context(
    *,
    diff_text: str,
    generated_paths: list[str],
    vendor_paths: list[str],
    max_lines: int = 240,
) -> dict[str, Any]:
    """Build deterministic low-cost fallback context for fast-path failures."""
    file_path = ""
    file_stats: dict[str, Counter[str]] = {}
    kept_lines: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            tokens = line.split(" ")
            if len(tokens) >= 4:
                candidate = tokens[2]
                file_path = candidate[2:] if candidate.startswith("a/") else candidate
                file_stats.setdefault(file_path, Counter())
        if _is_low_signal_file(file_path, generated_paths=generated_paths, vendor_paths=vendor_paths):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            file_stats[file_path]["added"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            file_stats[file_path]["removed"] += 1
        elif line.startswith("@@"):
            file_stats[file_path]["hunks"] += 1
        if len(kept_lines) < max_lines:
            kept_lines.append(line[:400])

    extension_histogram: Counter[str] = Counter()
    manifest: list[str] = []
    for path in sorted(file_stats.keys()):
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else "(none)"
        extension_histogram[ext] += 1
        stats = file_stats[path]
        manifest.append(
            f"{path} (+{stats.get('added', 0)} -{stats.get('removed', 0)} hunks:{stats.get('hunks', 0)})"
        )
    return {
        "compacted_diff_excerpt": "\n".join(kept_lines),
        "manifest": manifest,
        "extension_histogram": dict(sorted(extension_histogram.items())),
        "line_budget": max_lines,
    }


def _is_low_signal_file(path: str, *, generated_paths: list[str], vendor_paths: list[str]) -> bool:
    lockfile_markers = ("pnpm-lock.yaml", "package-lock.json", "yarn.lock", "poetry.lock", "uv.lock")
    if any(marker in path for marker in lockfile_markers):
        return True
    if any(fnmatch(path, pattern) for pattern in generated_paths):
        return True
    return any(fnmatch(path, pattern) for pattern in vendor_paths)
