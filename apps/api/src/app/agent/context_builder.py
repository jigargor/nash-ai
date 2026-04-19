from dataclasses import dataclass
from fnmatch import fnmatch
import hashlib

import tiktoken

from app.agent.diff_parser import FileInDiff, NumberedLine, right_side_diff_line_set
from app.agent.review_config import ContextPackagingConfig
from app.agent.schema import ContextAnchor, ContextBudgets, ContextSegment, LayeredContextPackage
from app.github.client import GitHubClient

ENCODER = tiktoken.get_encoding("cl100k_base")
MAX_INPUT_TOKENS = 100_000
MAX_DIFF_TOKENS = 50_000
CONTEXT_WINDOW_LINES = 30
DOC_CONTEXT_WINDOW_LINES = 8
SUMMARY_CACHE: dict[str, str] = {}


@dataclass
class ContextBundle:
    rendered: str
    fetched_files: dict[str, str]
    package: LayeredContextPackage
    telemetry: dict[str, object]


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
    *,
    budgets: ContextBudgets | None = None,
    packaging: ContextPackagingConfig | None = None,
    repo_segments: list[str] | None = None,
) -> ContextBundle:
    active_budgets = budgets or ContextBudgets()
    active_packaging = packaging or ContextPackagingConfig()
    package = LayeredContextPackage()
    fetched_files: dict[str, str] = {}
    dropped_segments: list[str] = []
    included_files = _pick_files_for_review(files_in_diff, active_packaging)
    required_anchor_lines = right_side_diff_line_set(included_files)
    included_anchor_lines: set[tuple[str, int]] = set()

    token_usage = {
        "project": 0,
        "repo": 0,
        "review_diff_hunks": 0,
        "review_surrounding": 0,
    }

    project_text = (
        "Project context: prioritize correctness/security findings, use exact file/line anchors, "
        "and fetch file content before suggesting edits if uncertain."
    )
    project_segment = _make_segment(layer="project", source_id="project-policy", fidelity="high", text=project_text)
    if project_segment.token_count <= active_budgets.system_prompt:
        package.project.append(project_segment)
        token_usage["project"] += project_segment.token_count
    else:
        dropped_segments.append("project-policy")

    for index, text in enumerate(repo_segments or []):
        normalized = text.strip()
        if not normalized:
            continue
        segment = _make_segment(
            layer="repo",
            source_id=f"repo-segment-{index + 1}",
            fidelity="high",
            text=normalized,
        )
        if token_usage["repo"] + segment.token_count > active_budgets.repo_profile:
            dropped_segments.append(segment.source_id)
            continue
        package.repo.append(segment)
        token_usage["repo"] += segment.token_count

    summary_calls = 0
    for file_in_diff in included_files:
        source = await _try_fetch_file(gh, owner, repo, file_in_diff.path, head_sha)
        if source is None:
            dropped_segments.append(f"{file_in_diff.path}:fetch_failed")
            continue
        fetched_files[file_in_diff.path] = source
        file_lines = source.splitlines()
        file_in_diff.context_window = _build_context_window(file_in_diff, source)
        is_generated = _is_generated_file(file_in_diff.path, source, active_packaging.generated_paths)
        is_lockfile = _is_lockfile(file_in_diff.path)
        hunks = _build_hunks(file_in_diff.numbered_lines)
        for hunk_index, hunk in enumerate(hunks, start=1):
            score = _score_hunk(file_in_diff, hunk, is_generated=is_generated, is_lockfile=is_lockfile)
            hunk_text = _render_hunk(file_in_diff.path, file_in_diff.language, hunk_index, hunk)
            hunk_segment = _make_segment(
                layer="review",
                source_id=f"{file_in_diff.path}:hunk:{hunk_index}",
                fidelity="high",
                text=hunk_text,
                file_path=file_in_diff.path,
                line_start=_hunk_anchor_line(hunk),
                line_end=_hunk_end_line(hunk),
                score=score,
            )
            if token_usage["review_diff_hunks"] + hunk_segment.token_count > active_budgets.diff_hunks:
                dropped_segments.append(hunk_segment.source_id)
                continue
            package.review.append(hunk_segment)
            token_usage["review_diff_hunks"] += hunk_segment.token_count

            if is_generated or is_lockfile:
                continue
            window_size = DOC_CONTEXT_WINDOW_LINES if _is_docs_file(file_in_diff.path, file_in_diff.language) else CONTEXT_WINDOW_LINES
            context_text = _render_surrounding_context(file_lines, hunk, window_size=window_size)
            if not context_text:
                continue
            context_segment = _make_segment(
                layer="review",
                source_id=f"{file_in_diff.path}:context:{hunk_index}",
                fidelity="high",
                text=context_text,
                file_path=file_in_diff.path,
                line_start=_hunk_anchor_line(hunk),
                line_end=_hunk_end_line(hunk),
                score=score,
            )
            if token_usage["review_surrounding"] + context_segment.token_count <= active_budgets.surrounding_context:
                package.review.append(context_segment)
                token_usage["review_surrounding"] += context_segment.token_count
                continue

            if not active_packaging.summarization_enabled:
                dropped_segments.append(context_segment.source_id)
                continue
            if summary_calls >= active_packaging.max_summary_calls_per_review:
                dropped_segments.append(f"{context_segment.source_id}:summary_cap_reached")
                continue

            summary_segment = _make_segment(
                layer="review",
                source_id=f"{context_segment.source_id}:summary",
                fidelity="summary",
                text=_summarize_context_segment(file_in_diff.path, context_text),
                file_path=file_in_diff.path,
                line_start=context_segment.line_start,
                line_end=context_segment.line_end,
                score=score,
            )
            summary_calls += 1
            package.summarization_used = True
            package.summarization_calls = summary_calls
            if token_usage["review_surrounding"] + summary_segment.token_count <= active_budgets.surrounding_context:
                package.review.append(summary_segment)
                token_usage["review_surrounding"] += summary_segment.token_count
            else:
                dropped_segments.append(summary_segment.source_id)

        required_in_file = [line for path, line in required_anchor_lines if path == file_in_diff.path]
        for line_no in required_in_file:
            if line_no - 1 < 0 or line_no - 1 >= len(file_lines):
                continue
            package.anchors.append(
                ContextAnchor(
                    file_path=file_in_diff.path,
                    line_no=line_no,
                    line_content=file_lines[line_no - 1],
                )
            )
            included_anchor_lines.add((file_in_diff.path, line_no))

    package.dropped_segments = dropped_segments
    package.ignored_anchor_files = _ignored_anchor_files(files_in_diff, included_files)
    if required_anchor_lines:
        package.anchor_coverage = len(included_anchor_lines) / len(required_anchor_lines)
    else:
        package.anchor_coverage = 1.0
    if package.anchor_coverage < 1.0:
        raise RuntimeError(
            f"Context packer anchor coverage invariant failed: {package.anchor_coverage:.3f} (expected 1.000)"
        )

    partial_note = _partial_review_note(files_in_diff, included_files, active_packaging)
    if partial_note:
        package.partial_review_mode = True
        package.partial_review_note = partial_note
        package.repo.append(
            _make_segment(
                layer="repo",
                source_id="partial-review-note",
                fidelity="reference",
                text=partial_note,
            )
        )

    package.dropped_segments = dropped_segments
    rendered = _render_package(package)
    telemetry: dict[str, object] = {
        "layer_token_usage": token_usage,
        "dropped_segments": dropped_segments,
        "anchor_coverage": package.anchor_coverage,
        "summarization_used": package.summarization_used,
        "summarization_calls": package.summarization_calls,
        "partial_review_mode": package.partial_review_mode,
    }
    return ContextBundle(rendered=rendered, fetched_files=fetched_files, package=package, telemetry=telemetry)


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


def _hunk_end_line(hunk: list[NumberedLine]) -> int:
    end_line = _hunk_anchor_line(hunk)
    for numbered_line in hunk:
        if numbered_line.new_line_no is not None:
            end_line = max(end_line, numbered_line.new_line_no)
    return end_line


def _render_hunk(path: str, language: str, hunk_index: int, hunk: list[NumberedLine]) -> str:
    lines = [f"## File: {path} ({language})", "", f"Hunk {hunk_index} (around line {_hunk_anchor_line(hunk)}):"]
    for numbered_line in hunk:
        line_no = str(numbered_line.new_line_no) if numbered_line.new_line_no is not None else "-"
        marker = {"add": "+", "del": "-", "ctx": "ctx"}[numbered_line.kind]
        lines.append(f"  {line_no:>4} | {marker:^3} | {numbered_line.content}")
    return "\n".join(lines)


def _render_surrounding_context(file_lines: list[str], hunk: list[NumberedLine], *, window_size: int) -> str:
    anchor = _hunk_anchor_line(hunk)
    end = _hunk_end_line(hunk)
    start_line = max(1, anchor - window_size)
    end_line = min(len(file_lines), end + window_size)
    if start_line > end_line:
        return ""
    out = [f"### Surrounding context (lines {start_line}-{end_line}):"]
    for line_no in range(start_line, end_line + 1):
        out.append(f"  {line_no}: {file_lines[line_no - 1]}")
    return "\n".join(out)


def _score_hunk(file_in_diff: FileInDiff, hunk: list[NumberedLine], *, is_generated: bool, is_lockfile: bool) -> float:
    changed_lines = sum(1 for line in hunk if line.kind == "add")
    language_weight = {
        "Python": 1.0,
        "TypeScript": 1.0,
        "TypeScript React": 0.9,
        "JavaScript": 0.9,
        "Rust": 1.0,
        "Go": 0.95,
        "SQL": 1.0,
        "Markdown": 0.4,
        "JSON": 0.3,
        "YAML": 0.5,
        "TOML": 0.4,
        "Text": 0.2,
    }.get(file_in_diff.language, 0.5)
    path = file_in_diff.path.lower()
    path_weight = 0.0
    for token, weight in (
        ("auth", 1.2),
        ("security", 1.2),
        ("migration", 1.1),
        ("db", 0.9),
        ("payment", 1.2),
        ("api", 0.8),
        ("test", -0.4),
        ("docs", -0.6),
    ):
        if token in path:
            path_weight += weight
    generated_penalty = 3.0 if is_generated else 0.0
    lockfile_penalty = 2.0 if is_lockfile else 0.0
    oversize_penalty = max(0, len(hunk) - 40) * 0.03
    return (2.0 * changed_lines) + (1.5 * language_weight) + path_weight - generated_penalty - lockfile_penalty - oversize_penalty


def _is_generated_file(path: str, source: str, configured_patterns: list[str]) -> bool:
    lowered = path.lower()
    generated_markers = [
        "this file was automatically generated",
        "generated by",
        "@generated",
        "do not edit",
    ]
    if source and any(marker in source.lower()[:300] for marker in generated_markers):
        return True
    if "__generated__" in lowered or "generated" in lowered:
        return True
    return any(fnmatch(path, pattern) for pattern in configured_patterns)


def _is_docs_file(path: str, language: str) -> bool:
    return language == "Markdown" or path.lower().endswith(".md")


def _is_lockfile(path: str) -> bool:
    lockfiles = {
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
        "uv.lock",
        "cargo.lock",
    }
    return path.lower().split("/")[-1] in lockfiles


def _is_vendored(path: str, configured_vendor_paths: list[str]) -> bool:
    lowered = path.lower()
    if lowered.startswith("vendor/") or lowered.startswith("third_party/"):
        return True
    return any(fnmatch(path, pattern) for pattern in configured_vendor_paths)


def _make_segment(
    *,
    layer: str,
    source_id: str,
    fidelity: str,
    text: str,
    file_path: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
    score: float | None = None,
) -> ContextSegment:
    normalized = text.strip()
    return ContextSegment(
        layer=layer,
        source_id=source_id,
        fidelity=fidelity,
        text=normalized,
        token_count=count_tokens(normalized),
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        score=score,
    )


def _pick_files_for_review(files_in_diff: list[FileInDiff], packaging: ContextPackagingConfig) -> list[FileInDiff]:
    ranked: list[tuple[float, FileInDiff, int]] = []
    total_changed_non_generated = 0
    for file_in_diff in files_in_diff:
        if _is_vendored(file_in_diff.path, packaging.vendor_paths):
            continue
        changed_count = sum(1 for line in file_in_diff.numbered_lines if line.kind == "add" and line.new_line_no is not None)
        if changed_count == 0:
            continue
        is_generated = _is_generated_file(file_in_diff.path, "", packaging.generated_paths)
        if not is_generated:
            total_changed_non_generated += changed_count
        score = 2.0 * changed_count + (0.8 if "test" not in file_in_diff.path.lower() else -0.3)
        ranked.append((score, file_in_diff, changed_count))

    if not packaging.partial_review_mode_enabled or total_changed_non_generated <= packaging.partial_review_changed_lines_threshold:
        return [item[1] for item in sorted(ranked, key=lambda entry: entry[0], reverse=True)]

    selected: list[FileInDiff] = []
    running_changed = 0
    for _, file_in_diff, changed_count in sorted(ranked, key=lambda entry: entry[0], reverse=True):
        if running_changed >= packaging.partial_review_changed_lines_threshold:
            break
        selected.append(file_in_diff)
        running_changed += changed_count
    return selected


def _partial_review_note(
    all_files: list[FileInDiff],
    included_files: list[FileInDiff],
    packaging: ContextPackagingConfig,
) -> str | None:
    all_changed = sum(1 for file in all_files for line in file.numbered_lines if line.kind == "add" and line.new_line_no is not None)
    included_changed = sum(
        1
        for file in included_files
        for line in file.numbered_lines
        if line.kind == "add" and line.new_line_no is not None
    )
    if not packaging.partial_review_mode_enabled:
        return None
    if all_changed <= packaging.partial_review_changed_lines_threshold:
        return None
    return (
        "This pull request exceeded the configured changed-line threshold. "
        f"Review scope was limited to the highest-priority files ({included_changed}/{all_changed} changed lines)."
    )


def _render_package(package: LayeredContextPackage) -> str:
    sections: list[str] = []
    if package.project:
        sections.append("## Project context")
        sections.extend(segment.text for segment in package.project)
    if package.repo:
        sections.append("## Repository context")
        sections.extend(segment.text for segment in package.repo)
    if package.review:
        sections.append("## Review context")
        sections.extend(segment.text for segment in package.review)
    if package.anchors:
        sections.append("## Anchor map (content-validated)")
        for anchor in package.anchors:
            sections.append(f"- {anchor.file_path}:{anchor.line_no} => {anchor.line_content}")
    return "\n\n".join(sections)


def _summarize_context_segment(path: str, context_text: str) -> str:
    digest = hashlib.sha1(f"{path}:{context_text}".encode("utf-8")).hexdigest()
    if digest in SUMMARY_CACHE:
        return SUMMARY_CACHE[digest]
    lines = [line.strip() for line in context_text.splitlines() if line.strip()]
    signatures = [line for line in lines if line.startswith(("def ", "async def ", "class ", "function ", "export "))]
    summary = [
        f"### Structured summary for {path}",
        f"- total_lines: {len(lines)}",
        f"- signatures: {len(signatures)}",
    ]
    for signature in signatures[:6]:
        summary.append(f"- signature: {signature[:120]}")
    if not signatures:
        for sample in lines[:5]:
            summary.append(f"- sample: {sample[:120]}")
    rendered = "\n".join(summary)
    SUMMARY_CACHE[digest] = rendered
    return rendered


def _ignored_anchor_files(all_files: list[FileInDiff], included_files: list[FileInDiff]) -> list[str]:
    included = {file.path for file in included_files}
    return sorted(file.path for file in all_files if file.path not in included)
