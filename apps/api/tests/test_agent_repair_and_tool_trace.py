from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.repair import repair_finding, repair_findings_from_files
from app.agent.schema import Finding
from app.agent.tool_trace import extract_tool_call_history, extract_tool_usage_by_file

FILE_PATH = "app.py"
FILE_LINES = [
    "import os",
    "",
    "def load():",
    "    token = os.environ['TOKEN']",
    "    return token",
    "",
    "def main():",
    "    print(load())",
]
FILE_CONTENT = "\n".join(FILE_LINES)


def _finding(**overrides: object) -> Finding:
    payload: dict[str, object] = {
        "severity": "medium",
        "category": "security",
        "message": "Secret read from environment without validation.",
        "file_path": FILE_PATH,
        "line_start": 4,
        "target_line_content": "    token = os.environ['TOKEN']",
        "confidence": 80,
        "evidence": "diff_visible",
    }
    payload.update(overrides)
    return Finding.model_validate(payload)


def _files(content: str = FILE_CONTENT) -> dict[str, str]:
    return {FILE_PATH: content}


# ---------------------------------------------------------------------------
# repair_finding
# ---------------------------------------------------------------------------


def test_repair_finding_exact_line_match_normalizes_target_line_content() -> None:
    finding = _finding(line_start=4, target_line_content="\ttoken = os.environ['TOKEN']   ")

    repaired = repair_finding(finding, _files(), commentable_lines=None, window=3)

    assert repaired is finding
    assert repaired.line_start == 4
    assert repaired.line_end is None
    assert repaired.target_line_content == FILE_LINES[3]


def test_repair_finding_drifted_line_within_window_reanchors_line_range() -> None:
    finding = _finding(line_start=2, line_end=3)

    repaired = repair_finding(finding, _files(), commentable_lines=None, window=3)

    assert repaired.line_start == 4
    assert repaired.line_end == 5
    assert repaired.target_line_content == FILE_LINES[3]


def test_repair_finding_drifted_line_matches_after_whitespace_normalization() -> None:
    finding = _finding(line_start=1, target_line_content="\ttoken = os.environ['TOKEN']")

    repaired = repair_finding(finding, _files(), commentable_lines=None, window=3)

    assert repaired.line_start == 4
    assert repaired.line_end == 4
    assert repaired.target_line_content == FILE_LINES[3]


def test_repair_finding_reanchor_clamps_line_end_to_file_length() -> None:
    finding = _finding(
        line_start=5,
        line_end=7,
        target_line_content="    print(load())",
    )

    repaired = repair_finding(finding, _files(), commentable_lines=None, window=3)

    assert repaired.line_start == 8
    assert repaired.line_end == 8
    assert repaired.target_line_content == FILE_LINES[7]


def test_repair_finding_drifted_line_outside_window_is_unchanged() -> None:
    finding = _finding(line_start=1, target_line_content="    print(load())")

    repaired = repair_finding(finding, _files(), commentable_lines=None, window=2)

    assert repaired.line_start == 1
    assert repaired.line_end is None
    assert repaired.target_line_content == "    print(load())"


def test_repair_finding_missing_file_returns_finding_unchanged() -> None:
    finding = _finding(line_start=1)
    before = finding.model_dump()

    repaired = repair_finding(finding, {"other.py": FILE_CONTENT}, commentable_lines=None, window=3)

    assert repaired is finding
    assert repaired.model_dump() == before


def test_repair_finding_line_start_beyond_file_returns_unchanged() -> None:
    finding = _finding(line_start=50)
    before = finding.model_dump()

    repaired = repair_finding(finding, _files(), commentable_lines=None, window=100)

    assert repaired.model_dump() == before


def test_repair_finding_commentable_lines_restriction_prevents_reanchor() -> None:
    finding = _finding(line_start=2, line_end=3)
    commentable = {(FILE_PATH, 2), (FILE_PATH, 3), (FILE_PATH, 4)}

    repaired = repair_finding(finding, _files(), commentable_lines=commentable, window=3)

    assert repaired.line_start == 2
    assert repaired.line_end == 3
    assert repaired.target_line_content == "    token = os.environ['TOKEN']"


def test_repair_finding_commentable_range_allows_reanchor() -> None:
    finding = _finding(line_start=2, line_end=3)
    commentable = {(FILE_PATH, 4), (FILE_PATH, 5)}

    repaired = repair_finding(finding, _files(), commentable_lines=commentable, window=3)

    assert repaired.line_start == 4
    assert repaired.line_end == 5


def test_repair_finding_commentable_lines_for_other_file_block_reanchor() -> None:
    finding = _finding(line_start=2)
    commentable = {("other.py", 4)}

    repaired = repair_finding(finding, _files(), commentable_lines=commentable, window=3)

    assert repaired.line_start == 2


def test_repair_finding_exact_match_ignores_commentable_lines() -> None:
    finding = _finding(line_start=4)

    repaired = repair_finding(finding, _files(), commentable_lines=set(), window=3)

    assert repaired.line_start == 4
    assert repaired.target_line_content == FILE_LINES[3]


# ---------------------------------------------------------------------------
# repair_findings_from_files
# ---------------------------------------------------------------------------


def test_repair_findings_from_files_repairs_each_finding_in_order() -> None:
    exact = _finding(line_start=4, target_line_content="\ttoken = os.environ['TOKEN']")
    drifted = _finding(line_start=6, target_line_content="    print(load())")
    missing = _finding(file_path="missing.py", line_start=1, target_line_content="nope")

    repaired = repair_findings_from_files(
        [exact, drifted, missing],
        _files(),
        commentable_lines=None,
        window=3,
    )

    assert [f.line_start for f in repaired] == [4, 8, 1]
    assert repaired[0].target_line_content == FILE_LINES[3]
    assert repaired[1].target_line_content == FILE_LINES[7]
    assert repaired[2].target_line_content == "nope"


def test_repair_findings_from_files_with_empty_input_returns_empty_list() -> None:
    assert repair_findings_from_files([], _files(), commentable_lines=None, window=3) == []


# ---------------------------------------------------------------------------
# extract_tool_usage_by_file
# ---------------------------------------------------------------------------


def _tool_use(name: str, tool_input: object) -> dict[str, object]:
    return {"type": "tool_use", "id": f"call-{name}", "name": name, "input": tool_input}


def test_extract_tool_usage_by_file_collects_path_and_file_path_from_dict_blocks() -> None:
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "Review this PR."},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me look."},
                _tool_use("fetch_file_content", {"path": "  src/app.py  "}),
                _tool_use("get_file_history", {"file_path": "src/util.py"}),
                _tool_use("fetch_file_content", {"path": "src/app.py"}),
            ],
        },
    ]

    assert extract_tool_usage_by_file(messages) == {"src/app.py", "src/util.py"}


def test_extract_tool_usage_by_file_accepts_object_style_blocks() -> None:
    block = SimpleNamespace(
        type="tool_use",
        name="read_file_range",
        input={"path": "lib/core.py", "start_line": 1, "end_line": 5},
    )
    text_block = SimpleNamespace(type="text", text="thinking")
    messages: list[dict[str, object]] = [{"role": "assistant", "content": [text_block, block]}]

    assert extract_tool_usage_by_file(messages) == {"lib/core.py"}


def test_extract_tool_usage_by_file_skips_non_list_content() -> None:
    messages: list[dict[str, object]] = [
        {"role": "assistant", "content": "plain string"},
        {"role": "assistant", "content": {"type": "tool_use", "input": {"path": "a.py"}}},
        {"role": "assistant"},
    ]

    assert extract_tool_usage_by_file(messages) == set()


def test_extract_tool_usage_by_file_skips_blocks_without_usable_path() -> None:
    messages: list[dict[str, object]] = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "search_codebase"},
                _tool_use("search_codebase", "not-a-dict"),
                _tool_use("search_codebase", {"pattern": "jwt"}),
                _tool_use("fetch_file_content", {"path": "   "}),
                _tool_use("fetch_file_content", {"path": 42}),
                {"type": "tool_result", "content": [{"path": "ignored.py"}]},
                SimpleNamespace(type="tool_use", name="fetch_file_content", input="nope"),
            ],
        }
    ]

    assert extract_tool_usage_by_file(messages) == set()


# ---------------------------------------------------------------------------
# extract_tool_call_history
# ---------------------------------------------------------------------------


def test_extract_tool_call_history_returns_name_and_input_in_order() -> None:
    messages: list[dict[str, object]] = [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Checking."},
                _tool_use("fetch_file_content", {"path": "a.py"}),
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "content": "..."}]},
        {
            "role": "assistant",
            "content": [_tool_use("search_codebase", {"pattern": "jwt", "path_glob": "src"})],
        },
    ]

    assert extract_tool_call_history(messages) == [
        {"name": "fetch_file_content", "input": {"path": "a.py"}},
        {"name": "search_codebase", "input": {"pattern": "jwt", "path_glob": "src"}},
    ]


def test_extract_tool_call_history_accepts_object_style_blocks() -> None:
    block = SimpleNamespace(type="tool_use", name="list_directory", input={"path": "src"})
    messages: list[dict[str, object]] = [{"role": "assistant", "content": [block]}]

    assert extract_tool_call_history(messages) == [
        {"name": "list_directory", "input": {"path": "src"}}
    ]


def test_extract_tool_call_history_skips_non_list_content() -> None:
    messages: list[dict[str, object]] = [
        {"role": "assistant", "content": "no blocks here"},
        {"role": "assistant", "content": None},
    ]

    assert extract_tool_call_history(messages) == []


def test_extract_tool_call_history_skips_blocks_without_name_or_input() -> None:
    messages: list[dict[str, object]] = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "input": {"path": "a.py"}},
                {"type": "tool_use", "name": "", "input": {"path": "a.py"}},
                {"type": "tool_use", "name": "fetch_file_content"},
                {"type": "tool_use", "name": "fetch_file_content", "input": ["a.py"]},
                {"type": "text", "name": "fetch_file_content", "input": {"path": "a.py"}},
                SimpleNamespace(type="tool_use", name=123, input={"path": "a.py"}),
                SimpleNamespace(type="tool_use", name="search_codebase", input=None),
                _tool_use("get_file_history", {"path": "kept.py"}),
            ],
        }
    ]

    assert extract_tool_call_history(messages) == [
        {"name": "get_file_history", "input": {"path": "kept.py"}}
    ]


@pytest.mark.parametrize("messages", [[], [{"role": "user", "content": []}]])
def test_extract_helpers_with_no_tool_blocks_return_empty(
    messages: list[dict[str, object]],
) -> None:
    assert extract_tool_usage_by_file(messages) == set()
    assert extract_tool_call_history(messages) == []
