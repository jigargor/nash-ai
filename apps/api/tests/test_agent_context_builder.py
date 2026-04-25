import asyncio

from app.agent.context_builder import build_context_bundle
from app.agent.diff_parser import parse_diff
from app.agent.review_config import ContextPackagingConfig
from app.agent.schema import ContextBudgets


class FakeGitHubClient:
    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        assert owner == "acme"
        assert repo == "demo"
        assert path == "app.py"
        return "\n".join([f"line_{index}" for index in range(1, 220)])


class FakeGitHubClientFetchFails:
    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        raise RuntimeError("simulated fetch failure")


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
            budgets=ContextBudgets(diff_hunks=2000, surrounding_context=2000),
            packaging=ContextPackagingConfig(partial_review_mode_enabled=False),
        )
    )

    assert "## Project context" in bundle.rendered
    assert "## Review context" in bundle.rendered
    assert "## File: app.py (Python)" in bundle.rendered
    assert "Hunk 1 (around line 145)" in bundle.rendered
    assert "145 |  +  | value = new_call()" in bundle.rendered
    assert "### Surrounding context (lines 115-176):" in bundle.rendered
    assert bundle.package.anchor_coverage == 1.0
    assert bundle.telemetry.anchor_coverage == 1.0
    assert bundle.fetched_files["app.py"].startswith("line_1")


def test_build_context_bundle_keeps_anchor_coverage_when_file_fetch_fails() -> None:
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
            FakeGitHubClientFetchFails(),
            owner="acme",
            repo="demo",
            head_sha="abc123",
            files_in_diff=files,
            budgets=ContextBudgets(diff_hunks=2000, surrounding_context=2000),
            packaging=ContextPackagingConfig(partial_review_mode_enabled=False),
        )
    )

    assert bundle.package.anchor_coverage == 1.0
    assert bundle.telemetry.anchor_coverage == 1.0
    assert bundle.fetched_files == {}
    assert "## Anchor map (content-validated)" in bundle.rendered
    assert "app.py:145 => value = new_call()" in bundle.rendered


def test_context_bundle_quality_at_cost_curve_keeps_anchor_coverage() -> None:
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
    small_bundle = asyncio.run(
        build_context_bundle(
            FakeGitHubClient(),
            owner="acme",
            repo="demo",
            head_sha="abc123",
            files_in_diff=files,
            budgets=ContextBudgets(diff_hunks=120, surrounding_context=80),
            packaging=ContextPackagingConfig(partial_review_mode_enabled=False),
        )
    )
    large_bundle = asyncio.run(
        build_context_bundle(
            FakeGitHubClient(),
            owner="acme",
            repo="demo",
            head_sha="abc123",
            files_in_diff=parse_diff(diff_text),
            budgets=ContextBudgets(diff_hunks=5000, surrounding_context=5000),
            packaging=ContextPackagingConfig(partial_review_mode_enabled=False),
        )
    )

    small_tokens = sum(segment.token_count for segment in small_bundle.package.review)
    large_tokens = sum(segment.token_count for segment in large_bundle.package.review)
    assert large_tokens >= small_tokens
    assert small_bundle.package.anchor_coverage == 1.0
    assert large_bundle.package.anchor_coverage == 1.0
