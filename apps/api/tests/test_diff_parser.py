from app.agent.diff_parser import parse_diff


def test_parse_diff_extracts_numbered_lines() -> None:
    diff_text = """diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-print("old")
+print("new")
 print("same")
"""
    files = parse_diff(diff_text)
    assert len(files) == 1
    assert files[0].path == "a.py"
    assert files[0].language == "Python"
    assert files[0].numbered_lines[0].kind == "del"
    assert files[0].numbered_lines[0].new_line_no is None
    assert files[0].numbered_lines[0].old_line_no == 1
    assert files[0].numbered_lines[1].kind == "add"
    assert files[0].numbered_lines[1].new_line_no == 1
    assert files[0].numbered_lines[1].old_line_no is None
