import tiktoken

from app.agent.diff_parser import DiffHunk
from app.github.client import GitHubClient

ENCODER = tiktoken.get_encoding("cl100k_base")
MAX_INPUT_TOKENS = 100_000
MAX_DIFF_TOKENS = 50_000


def count_tokens(text: str) -> int:
    return len(ENCODER.encode(text))


def fits_in_budget(messages: list[dict], remaining: int) -> bool:
    total = sum(count_tokens(str(message)) for message in messages)
    return total < remaining


def is_diff_too_large(diff_text: str) -> bool:
    return count_tokens(diff_text) > MAX_DIFF_TOKENS


async def build_context_bundle(
    gh: GitHubClient,
    owner: str,
    repo: str,
    head_sha: str,
    hunks: list[DiffHunk],
) -> str:
    files = sorted({hunk.file for hunk in hunks})
    sections: list[str] = []
    for file_path in files:
        try:
            source = await gh.get_file_content(owner, repo, file_path, head_sha)
        except Exception:
            sections.append(f"### File: {file_path}\nUnable to fetch file content.\n")
            continue
        selected = _select_context(source, [h for h in hunks if h.file == file_path])
        sections.append(f"### File: {file_path}\n{selected}\n")
    return "\n".join(sections)


def _select_context(source: str, file_hunks: list[DiffHunk]) -> str:
    lines = source.splitlines()
    line_count = len(lines)
    if line_count <= 500:
        return source

    window = 50 if line_count <= 2000 else 30
    ranges = _build_ranges(file_hunks, window, line_count)
    selected_lines: list[str] = []
    for start, end in ranges:
        selected_lines.append(f"... lines {start}-{end} ...")
        selected_lines.extend(lines[start - 1 : end])
    return "\n".join(selected_lines)


def _build_ranges(hunks: list[DiffHunk], window: int, line_count: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for hunk in hunks:
        center = hunk.new_start or hunk.old_start or 1
        start = max(1, center - window)
        end = min(line_count, center + window)
        ranges.append((start, end))
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged
