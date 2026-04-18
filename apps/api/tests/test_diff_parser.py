from app.agent.diff_parser import parse_diff


def test_parse_diff_extracts_hunks() -> None:
    diff_text = """diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-print("old")
+print("new")
 print("same")
"""
    hunks = parse_diff(diff_text)
    assert len(hunks) == 1
    assert hunks[0].file == "a.py"
    assert hunks[0].changes[0].change_type == "del"
    assert hunks[0].changes[1].change_type == "add"
