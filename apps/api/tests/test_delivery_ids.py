from app.agent.schema import Finding
from app.delivery.ids import assign_finding_ids, stable_finding_id


def _finding(
    *,
    file_path: str = "src/app.py",
    line: int = 10,
    category: str = "security",
    message: str = "Do not eval user input.",
    target_line_content: str = "    x = eval(input())",
    finding_id: str | None = None,
) -> Finding:
    return Finding.model_validate(
        {
            "severity": "high",
            "category": category,
            "message": message,
            "file_path": file_path,
            "line_start": line,
            "target_line_content": target_line_content,
            "confidence": 90,
            "evidence": "diff_visible",
            "finding_id": finding_id,
        }
    )


def test_stable_finding_id_ignores_line_number_and_message() -> None:
    first = _finding(line=10, message="Do not eval user input.")
    shifted = _finding(line=42, message="Reworded: eval on untrusted data is unsafe.")

    assert stable_finding_id(first) == stable_finding_id(shifted)


def test_stable_finding_id_ignores_indentation_changes() -> None:
    first = _finding(target_line_content="    x = eval(input())")
    reindented = _finding(target_line_content="x  =  eval(input())")

    assert stable_finding_id(first) == stable_finding_id(reindented)


def test_stable_finding_id_changes_with_target_line_content() -> None:
    first = _finding(target_line_content="x = eval(input())")
    other = _finding(target_line_content="y = exec(input())")

    assert stable_finding_id(first) != stable_finding_id(other)


def test_stable_finding_id_changes_with_file_and_category() -> None:
    base = _finding()

    assert stable_finding_id(base) != stable_finding_id(_finding(file_path="src/other.py"))
    assert stable_finding_id(base) != stable_finding_id(_finding(category="performance"))


def test_assign_finding_ids_is_order_independent_and_keeps_existing_ids() -> None:
    a = _finding(target_line_content="a = 1")
    b = _finding(target_line_content="b = 2")
    preset = _finding(target_line_content="c = 3", finding_id="keep-me")

    forward = assign_finding_ids([a, b, preset])
    reverse = assign_finding_ids([preset, b, a])

    assert forward[0].finding_id == reverse[2].finding_id
    assert forward[1].finding_id == reverse[1].finding_id
    assert forward[2].finding_id == "keep-me"
    assert forward[0].finding_id != forward[1].finding_id
    assert not any("f0-" in (item.finding_id or "") for item in forward)
