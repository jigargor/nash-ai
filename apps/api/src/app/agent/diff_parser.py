from dataclasses import dataclass

from unidiff import PatchSet


@dataclass
class DiffChange:
    change_type: str
    line_num: int | None
    content: str


@dataclass
class DiffHunk:
    file: str
    old_start: int
    new_start: int
    changes: list[DiffChange]


def parse_diff(diff_text: str) -> list[DiffHunk]:
    patch = PatchSet(diff_text)
    hunks: list[DiffHunk] = []
    for patched_file in patch:
        for hunk in patched_file:
            changes: list[DiffChange] = []
            for line in hunk:
                if line.is_added:
                    change_type = "add"
                elif line.is_removed:
                    change_type = "del"
                else:
                    change_type = "ctx"
                changes.append(
                    DiffChange(
                        change_type=change_type,
                        line_num=line.target_line_no,
                        content=line.value.rstrip("\n"),
                    )
                )
            hunks.append(
                DiffHunk(
                    file=patched_file.path,
                    old_start=hunk.source_start,
                    new_start=hunk.target_start,
                    changes=changes,
                )
            )
    return hunks
