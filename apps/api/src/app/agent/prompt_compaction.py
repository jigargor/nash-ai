from __future__ import annotations

from collections import Counter

from app.agent.context_builder import count_tokens

_LOW_PRIORITY_PATH_TOKENS = ("lock", "yarn.lock", "pnpm-lock", "package-lock", "vendor")


def compact_diff_excerpt(diff_text: str, max_tokens: int) -> str:
    priority_lines: list[str] = []
    low_priority_lines: list[str] = []
    current_path = ""
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_path = _path_from_diff_header(raw_line)
            target = (
                low_priority_lines
                if any(token in current_path.lower() for token in _LOW_PRIORITY_PATH_TOKENS)
                else priority_lines
            )
            target.append(raw_line[:300])
            continue
        if not raw_line or raw_line.startswith(("index ", "@@", "--- ", "+++ ")):
            continue
        target = (
            low_priority_lines
            if any(token in current_path.lower() for token in _LOW_PRIORITY_PATH_TOKENS)
            else priority_lines
        )
        target.append(raw_line[:300])
    selected: list[str] = []
    token_total = 0
    for line in [*priority_lines, *low_priority_lines]:
        line_tokens = count_tokens(line)
        if selected and token_total + line_tokens > max_tokens:
            break
        selected.append(line)
        token_total += line_tokens
    return "\n".join(selected)


def extension_histogram(paths: list[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in paths:
        cleaned = path.rsplit("/", 1)[-1]
        if "." not in cleaned:
            counts["no_ext"] += 1
            continue
        counts[cleaned.rsplit(".", 1)[-1].lower()] += 1
    return dict(sorted(counts.items()))


def _path_from_diff_header(header: str) -> str:
    # diff --git a/path b/path
    parts = header.split()
    if len(parts) < 3:
        return ""
    left = parts[2]
    if left.startswith("a/"):
        return left[2:]
    return left
