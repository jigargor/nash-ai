import asyncio

from app.agent.context_builder import build_context_bundle
from app.agent.diff_parser import parse_diff


class FakeGitHubClient:
    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        assert owner == "acme"
        assert repo == "demo"
        assert path == "app.py"
        return "\n".join([f"line_{index}" for index in range(1, 220)])


def test_build_context_bundle_includes_numbered_hunks_and_surrounding_context() -> None:
    diff_text = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -145,2 +145,2 @@
-value = old_call()
+value = new_call()
 keep = "same"
"""
    files = parse_diff(diff_text)
    bundle = asyncio.run(
        build_context_bundle(
            FakeGitHubClient(),
            owner="acme",
            repo="demo",
            head_sha="abc123",
            files_in_diff=files,
        )
    )

    assert "## File: app.py (Python)" in bundle.rendered
    assert "Hunk 1 (around line 145)" in bundle.rendered
    assert "145 |  +  | value = new_call()" in bundle.rendered
    assert "### Surrounding context (lines 115-176):" in bundle.rendered
    assert bundle.fetched_files["app.py"].startswith("line_1")
