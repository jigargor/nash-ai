import tiktoken
from dataclasses import dataclass

from app.agent.diff_parser import FileInDiff, NumberedLine
from app.github.client import GitHubClient

ENCODER = tiktoken.get_encoding("cl100k_base")
MAX_INPUT_TOKENS = 100_000
MAX_DIFF_TOKENS = 50_000
CONTEXT_WINDOW_LINES = 30


@dataclass
class ContextBundle:
    rendered: str
    fetched_files: dict[str, str]


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
    files_in_diff: list[FileInDiff],
) -> ContextBundle:
    sections: list[str] = []
    fetched_files: dict[str, str] = {}
    for file_in_diff in files_in_diff:
        source = await _try_fetch_file(gh, owner, repo, file_in_diff.path, head_sha)
        if source is not None:
            fetched_files[file_in_diff.path] = source
            file_in_diff.context_window = _build_context_window(file_in_diff, source)
        sections.append(_format_file_section(file_in_diff, source_available=source is not None))
    return ContextBundle(rendered="\n\n".join(sections), fetched_files=fetched_files)


async def _try_fetch_file(
    gh: GitHubClient,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> str | None:
    try:
        return await gh.get_file_content(owner, repo, path, ref)
    except Exception:
        return None


def _build_context_window(file_in_diff: FileInDiff, source: str) -> list[tuple[int, str]]:
    lines = source.splitlines()
    if not lines:
        return []

    hunk_ranges = _build_hunk_ranges(file_in_diff.numbered_lines)
    if not hunk_ranges:
        return []

    context_ranges: list[tuple[int, int]] = []
    for start, end in hunk_ranges:
        context_start = max(1, start - CONTEXT_WINDOW_LINES)
        context_end = min(len(lines), end + CONTEXT_WINDOW_LINES)
        context_ranges.append((context_start, context_end))

    merged = _merge_ranges(context_ranges)
    context_lines: list[tuple[int, str]] = []
    for start, end in merged:
        for line_no in range(start, end + 1):
            context_lines.append((line_no, lines[line_no - 1]))
    return context_lines


def _build_hunk_ranges(numbered_lines: list[NumberedLine]) -> list[tuple[int, int]]:
    if not numbered_lines:
        return []

    ranges: list[tuple[int, int]] = []
    current_hunk: list[NumberedLine] = []
    previous_anchor: int | None = None

    for numbered_line in numbered_lines:
        anchor = numbered_line.new_line_no or numbered_line.old_line_no
        if not current_hunk:
            current_hunk.append(numbered_line)
            previous_anchor = anchor
            continue

        if anchor is not None and previous_anchor is not None and anchor > previous_anchor + 1:
            hunk_range = _hunk_to_range(current_hunk)
            if hunk_range:
                ranges.append(hunk_range)
            current_hunk = [numbered_line]
        else:
            current_hunk.append(numbered_line)
        previous_anchor = anchor if anchor is not None else previous_anchor

    hunk_range = _hunk_to_range(current_hunk)
    if hunk_range:
        ranges.append(hunk_range)

    return ranges


def _hunk_to_range(hunk: list[NumberedLine]) -> tuple[int, int] | None:
    new_lines = [line.new_line_no for line in hunk if line.new_line_no is not None]
    if not new_lines:
        return None
    return min(new_lines), max(new_lines)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    sorted_ranges = sorted(ranges)
    merged: list[tuple[int, int]] = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _format_file_section(file_in_diff: FileInDiff, source_available: bool) -> str:
    lines: list[str] = [f"## File: {file_in_diff.path} ({file_in_diff.language})", "", "### Diff hunks:", ""]
    for index, hunk in enumerate(_build_hunks(file_in_diff.numbered_lines), start=1):
        around = _hunk_anchor_line(hunk)
        lines.append(f"Hunk {index} (around line {around}):")
        for numbered_line in hunk:
            line_no = str(numbered_line.new_line_no) if numbered_line.new_line_no is not None else "-"
            marker = {"add": "+", "del": "-", "ctx": "ctx"}[numbered_line.kind]
            lines.append(f"  {line_no:>4} | {marker:^3} | {numbered_line.content}")
        lines.append("")

    if file_in_diff.context_window:
        start = file_in_diff.context_window[0][0]
        end = file_in_diff.context_window[-1][0]
        lines.append(f"### Surrounding context (lines {start}-{end}):")
        for line_no, code in file_in_diff.context_window:
            lines.append(f"  {line_no}: {code}")
    else:
        status = "unavailable for deleted file" if file_in_diff.is_deleted else "unavailable (fetch failed)"
        if not source_available and not file_in_diff.is_deleted:
            status = "unavailable (fetch failed)"
        lines.append(f"### Surrounding context: {status}")

    return "\n".join(lines)


def _build_hunks(numbered_lines: list[NumberedLine]) -> list[list[NumberedLine]]:
    if not numbered_lines:
        return []
    hunks: list[list[NumberedLine]] = []
    current: list[NumberedLine] = []
    previous_anchor: int | None = None
    for numbered_line in numbered_lines:
        anchor = numbered_line.new_line_no or numbered_line.old_line_no
        if not current:
            current.append(numbered_line)
            previous_anchor = anchor
            continue
        if anchor is not None and previous_anchor is not None and anchor > previous_anchor + 1:
            hunks.append(current)
            current = [numbered_line]
        else:
            current.append(numbered_line)
        previous_anchor = anchor if anchor is not None else previous_anchor
    if current:
        hunks.append(current)
    return hunks


def _hunk_anchor_line(hunk: list[NumberedLine]) -> int:
    for numbered_line in hunk:
        if numbered_line.new_line_no is not None:
            return numbered_line.new_line_no
    for numbered_line in hunk:
        if numbered_line.old_line_no is not None:
            return numbered_line.old_line_no
    return 1
