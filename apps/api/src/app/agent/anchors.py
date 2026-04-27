from app.agent.diff_parser import FileInDiff
from app.agent.schema import Finding
from typing import TypedDict


class DiffAnchorMetadata(TypedDict):
    new_line_no: int | None
    old_line_no: int | None
    hunk_id: str


def build_diff_anchor_index(files_in_diff: list[FileInDiff]) -> dict[tuple[str, int], DiffAnchorMetadata]:
    index: dict[tuple[str, int], DiffAnchorMetadata] = {}
    for file in files_in_diff:
        hunk_id = 0
        previous_line = -1
        for numbered in file.numbered_lines:
            anchor = numbered.new_line_no if numbered.new_line_no is not None else numbered.old_line_no
            if anchor is None:
                continue
            if previous_line != -1 and anchor > previous_line + 1:
                hunk_id += 1
            key = (file.path, anchor)
            index[key] = {
                "new_line_no": numbered.new_line_no,
                "old_line_no": numbered.old_line_no,
                "hunk_id": f"{file.path}:hunk:{hunk_id}",
            }
            previous_line = anchor
    return index


def attach_anchor_metadata(findings: list[Finding], files_in_diff: list[FileInDiff]) -> list[Finding]:
    index = build_diff_anchor_index(files_in_diff)
    updated: list[Finding] = []
    for finding in findings:
        anchor = index.get((finding.file_path, finding.line_start))
        if anchor is None:
            updated.append(finding)
            continue
        new_line_no = anchor["new_line_no"]
        old_line_no = anchor["old_line_no"]
        hunk_id = anchor["hunk_id"]
        finding.side = "RIGHT" if new_line_no is not None else "LEFT"
        finding.start_side = finding.side
        finding.old_line_no = old_line_no
        finding.new_line_no = new_line_no
        finding.patch_hunk = hunk_id
        updated.append(finding)
    return updated


def filter_findings_with_valid_anchors(findings: list[Finding], files_in_diff: list[FileInDiff]) -> list[Finding]:
    allowed = build_diff_anchor_index(files_in_diff)
    filtered: list[Finding] = []
    for finding in findings:
        anchor_line = finding.line_end or finding.line_start
        if (finding.file_path, anchor_line) not in allowed:
            continue
        filtered.append(finding)
    return filtered
