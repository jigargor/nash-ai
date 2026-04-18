from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from unidiff import PatchSet


@dataclass
class NumberedLine:
    new_line_no: int | None  # None for deleted lines
    old_line_no: int | None
    kind: Literal["add", "del", "ctx"]
    content: str


@dataclass
class FileInDiff:
    path: str
    language: str
    is_new: bool
    is_deleted: bool
    numbered_lines: list[NumberedLine]
    context_window: list[tuple[int, str]]


def parse_diff(diff_text: str) -> list[FileInDiff]:
    patch = PatchSet(diff_text)
    files: list[FileInDiff] = []
    for patched_file in patch:
        path = patched_file.path or patched_file.target_file.removeprefix("b/")
        numbered_lines: list[NumberedLine] = []
        for hunk in patched_file:
            for line in hunk:
                if line.is_added:
                    kind: Literal["add", "del", "ctx"] = "add"
                elif line.is_removed:
                    kind = "del"
                else:
                    kind = "ctx"
                numbered_lines.append(
                    NumberedLine(
                        new_line_no=line.target_line_no,
                        old_line_no=line.source_line_no,
                        kind=kind,
                        content=line.value.rstrip("\n"),
                    )
                )
        files.append(
            FileInDiff(
                path=path,
                language=_detect_language(path),
                is_new=patched_file.is_added_file,
                is_deleted=patched_file.is_removed_file,
                numbered_lines=numbered_lines,
                context_window=[],
            )
        )
    return files


def _detect_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    language_map = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript React",
        ".js": "JavaScript",
        ".jsx": "JavaScript React",
        ".go": "Go",
        ".rs": "Rust",
        ".sql": "SQL",
        ".json": "JSON",
        ".md": "Markdown",
        ".yml": "YAML",
        ".yaml": "YAML",
        ".toml": "TOML",
    }
    return language_map.get(ext, "Text")
