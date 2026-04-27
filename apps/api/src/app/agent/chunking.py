from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Literal

from app.agent.context_builder import count_tokens
from app.agent.diff_parser import FileInDiff

FileClass = Literal[
    "reviewable",
    "generated",
    "lockfile",
    "test_only",
    "config_only",
    "docs_only",
    "binary_unsupported",
    "deleted_only",
]


@dataclass(frozen=True)
class ClassifiedDiffFile:
    path: str
    file_class: FileClass
    changed_lines: int
    estimated_diff_tokens: int
    integration_key: str
    touched_package: str
    dependency_hint: str | None
    file_in_diff: FileInDiff


@dataclass(frozen=True)
class PlannedChunk:
    chunk_id: str
    files: tuple[ClassifiedDiffFile, ...]
    estimated_prompt_tokens: int
    estimated_output_tokens: int


@dataclass(frozen=True)
class ChunkPlan:
    chunks: tuple[PlannedChunk, ...]
    skipped_files: tuple[ClassifiedDiffFile, ...]
    is_partial: bool
    coverage_note: str
    total_estimated_prompt_tokens: int
    total_estimated_output_tokens: int
    touched_packages: tuple[str, ...]
    dependency_hints: tuple[str, ...]
    full_manifest: tuple[str, ...]


@dataclass(frozen=True)
class ChunkingPlannerConfig:
    enabled: bool = True
    proactive_threshold_tokens: int = 35_000
    target_chunk_tokens: int = 18_000
    max_chunks: int = 8
    min_files_per_chunk: int = 1
    include_file_classes: tuple[FileClass, ...] = ("reviewable", "config_only", "test_only")
    max_total_prompt_tokens: int = 120_000
    max_latency_seconds: int = 240
    output_headroom_tokens: int = 4_096


def classify_diff_files(
    diff_files: list[FileInDiff],
    *,
    generated_paths: list[str],
    vendor_paths: list[str],
) -> list[ClassifiedDiffFile]:
    classified: list[ClassifiedDiffFile] = []
    for file_in_diff in sorted(diff_files, key=lambda item: item.path):
        changed_lines = sum(1 for line in file_in_diff.numbered_lines if line.kind == "add" and line.new_line_no is not None)
        diff_text = _render_minimal_diff(file_in_diff)
        estimated_diff_tokens = count_tokens(diff_text)
        file_class = _classify_file(file_in_diff.path, file_in_diff.is_deleted, generated_paths, vendor_paths)
        touched_package = _package_hint(file_in_diff.path)
        dependency_hint = _dependency_hint(file_in_diff.path)
        classified.append(
            ClassifiedDiffFile(
                path=file_in_diff.path,
                file_class=file_class,
                changed_lines=changed_lines,
                estimated_diff_tokens=estimated_diff_tokens,
                integration_key=_integration_key(file_in_diff.path),
                touched_package=touched_package,
                dependency_hint=dependency_hint,
                file_in_diff=file_in_diff,
            )
        )
    return classified


def plan_chunks(
    diff_files: list[FileInDiff],
    planner_config: ChunkingPlannerConfig,
    *,
    pr_title: str,
    pr_body: str,
    generated_paths: list[str],
    vendor_paths: list[str],
) -> ChunkPlan:
    classified = classify_diff_files(
        diff_files,
        generated_paths=generated_paths,
        vendor_paths=vendor_paths,
    )
    skipped = tuple(file for file in classified if file.file_class not in planner_config.include_file_classes)
    review_surface = [file for file in classified if file.file_class in planner_config.include_file_classes]
    if not review_surface:
        return ChunkPlan(
            chunks=(),
            skipped_files=skipped,
            is_partial=False,
            coverage_note="No reviewable files after pre-pass classification.",
            total_estimated_prompt_tokens=0,
            total_estimated_output_tokens=0,
            touched_packages=(),
            dependency_hints=(),
            full_manifest=tuple(file.path for file in classified),
        )

    grouped = _group_by_integration(review_surface)
    shared_prompt_tokens = _shared_prompt_tokens(classified, pr_title=pr_title, pr_body=pr_body)
    chunks: list[PlannedChunk] = []
    active_files: list[ClassifiedDiffFile] = []
    active_tokens = 0
    for group in grouped:
        group_tokens = sum(file.estimated_diff_tokens for file in group)
        if (
            active_files
            and (active_tokens + group_tokens > planner_config.target_chunk_tokens)
            and len(active_files) >= planner_config.min_files_per_chunk
        ):
            chunks.append(
                _finalize_chunk(
                    chunk_index=len(chunks) + 1,
                    files=active_files,
                    shared_prompt_tokens=shared_prompt_tokens,
                    output_headroom_tokens=planner_config.output_headroom_tokens,
                )
            )
            active_files = []
            active_tokens = 0
        active_files.extend(group)
        active_tokens += group_tokens
    if active_files:
        chunks.append(
            _finalize_chunk(
                chunk_index=len(chunks) + 1,
                files=active_files,
                shared_prompt_tokens=shared_prompt_tokens,
                output_headroom_tokens=planner_config.output_headroom_tokens,
            )
        )

    partial = False
    if len(chunks) > planner_config.max_chunks:
        chunks = chunks[: planner_config.max_chunks]
        partial = True

    total_prompt = sum(chunk.estimated_prompt_tokens for chunk in chunks)
    total_output = sum(chunk.estimated_output_tokens for chunk in chunks)
    dependency_hints = tuple(sorted({hint for file in classified if (hint := file.dependency_hint) is not None}))
    touched_packages = tuple(sorted({file.touched_package for file in classified}))
    manifest = tuple(file.path for file in classified)
    coverage_note = _coverage_note(
        selected_chunks=chunks,
        review_surface=review_surface,
        skipped_files=skipped,
        partial=partial,
    )
    return ChunkPlan(
        chunks=tuple(chunks),
        skipped_files=skipped,
        is_partial=partial,
        coverage_note=coverage_note,
        total_estimated_prompt_tokens=total_prompt,
        total_estimated_output_tokens=total_output,
        touched_packages=touched_packages,
        dependency_hints=dependency_hints,
        full_manifest=manifest,
    )


def _classify_file(path: str, is_deleted: bool, generated_paths: list[str], vendor_paths: list[str]) -> FileClass:
    if is_deleted:
        return "deleted_only"
    lowered = path.lower()
    name = PurePosixPath(path).name.lower()
    if _is_binary_path(lowered):
        return "binary_unsupported"
    if _is_lockfile(name):
        return "lockfile"
    if _matches_any(path, generated_paths) or "generated" in lowered:
        return "generated"
    if _matches_any(path, vendor_paths):
        return "generated"
    if "/docs/" in lowered or lowered.endswith(".md"):
        return "docs_only"
    if _is_test_path(lowered):
        return "test_only"
    if _is_config_path(lowered):
        return "config_only"
    return "reviewable"


def _is_binary_path(path: str) -> bool:
    binary_exts = (
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".pdf",
        ".zip",
        ".gz",
        ".ico",
        ".woff",
        ".woff2",
    )
    return path.endswith(binary_exts)


def _is_lockfile(name: str) -> bool:
    return name in {"pnpm-lock.yaml", "package-lock.json", "yarn.lock", "poetry.lock", "uv.lock", "cargo.lock"}


def _is_test_path(path: str) -> bool:
    return "/tests/" in path or "/test/" in path or path.endswith("_test.py") or path.endswith(".spec.ts")


def _is_config_path(path: str) -> bool:
    config_exts = (".yml", ".yaml", ".toml", ".ini", ".cfg")
    if path.endswith(config_exts):
        return True
    return any(token in path for token in ("dockerfile", ".env", "pyproject.toml", "package.json", "tsconfig"))


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


def _package_hint(path: str) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    if parts:
        return parts[0]
    return "root"


def _dependency_hint(path: str) -> str | None:
    name = PurePosixPath(path).name.lower()
    if name in {"pyproject.toml", "uv.lock", "poetry.lock", "requirements.txt"}:
        return "python-dependencies"
    if name in {"package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock"}:
        return "node-dependencies"
    if name in {"cargo.toml", "cargo.lock"}:
        return "rust-dependencies"
    return None


def _integration_key(path: str) -> str:
    parts = list(PurePosixPath(path).parts)
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    if parts:
        return parts[0]
    return "root"


def _group_by_integration(files: list[ClassifiedDiffFile]) -> list[list[ClassifiedDiffFile]]:
    grouped: dict[str, list[ClassifiedDiffFile]] = {}
    for file in files:
        key = f"{file.integration_key}:{_feature_token(file.path)}"
        grouped.setdefault(key, []).append(file)
    ordered: list[list[ClassifiedDiffFile]] = []
    for key in sorted(grouped):
        ordered.append(sorted(grouped[key], key=lambda item: item.path))
    return ordered


def _feature_token(path: str) -> str:
    stem = PurePosixPath(path).stem.lower()
    if stem in {"index", "route", "utils", "types"}:
        return PurePosixPath(path).parent.name.lower() or stem
    return stem


def _shared_prompt_tokens(classified: list[ClassifiedDiffFile], *, pr_title: str, pr_body: str) -> int:
    manifest_lines = [file.path for file in classified]
    shared_payload = "\n".join(
        [
            f"PR title: {pr_title.strip()}",
            f"PR body: {pr_body.strip()}",
            "Changed file manifest:",
            *manifest_lines,
        ]
    )
    return count_tokens(shared_payload)


def _finalize_chunk(
    *,
    chunk_index: int,
    files: list[ClassifiedDiffFile],
    shared_prompt_tokens: int,
    output_headroom_tokens: int,
) -> PlannedChunk:
    diff_tokens = sum(file.estimated_diff_tokens for file in files)
    estimated_prompt_tokens = shared_prompt_tokens + diff_tokens
    return PlannedChunk(
        chunk_id=f"chunk-{chunk_index:03d}",
        files=tuple(files),
        estimated_prompt_tokens=estimated_prompt_tokens,
        estimated_output_tokens=output_headroom_tokens,
    )


def _coverage_note(
    *,
    selected_chunks: list[PlannedChunk],
    review_surface: list[ClassifiedDiffFile],
    skipped_files: tuple[ClassifiedDiffFile, ...],
    partial: bool,
) -> str:
    reviewed_paths = {file.path for chunk in selected_chunks for file in chunk.files}
    covered = len(reviewed_paths)
    total = len(review_surface)
    skipped = len(skipped_files)
    note = f"Chunked review coverage: {covered}/{total} review-surface files"
    if skipped:
        note += f"; {skipped} files skipped by pre-pass"
    if partial:
        note += "; truncated at max_chunks"
    return note + "."


def _render_minimal_diff(file_in_diff: FileInDiff) -> str:
    lines = [f"file: {file_in_diff.path}"]
    for numbered in file_in_diff.numbered_lines:
        marker = {"add": "+", "del": "-", "ctx": " "}[numbered.kind]
        lines.append(f"{marker} {numbered.content}")
    return "\n".join(lines)
