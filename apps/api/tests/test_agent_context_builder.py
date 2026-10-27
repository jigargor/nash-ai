import asyncio

from app.agent.context_builder import (
    HunkCandidate,
    build_context_bundle,
    fetch_sources_concurrently,
    rank_hunk_candidates,
)
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
    assert bundle.telemetry.observe_mode is True
    assert bundle.telemetry.pressure_state in {"green", "yellow", "orange", "red"}
    assert "L3_vs_L0" in bundle.telemetry.layer_duplication_tokens


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
    assert bundle.telemetry.poisoning_score >= 0.0


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
    assert large_bundle.telemetry.bloat_score >= 0.0


TWO_HUNK_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -10,2 +10,2 @@
-a = 1
+a = 2
 keep_low = True
@@ -100,2 +100,5 @@
 ctx_a
+n1 = 1
+n2 = 2
+n3 = 3
 ctx_b
"""


def _two_hunk_bundle(diff_hunks: int):  # type: ignore[no-untyped-def]
    return asyncio.run(
        build_context_bundle(
            FakeGitHubClient(),
            owner="acme",
            repo="demo",
            head_sha="abc123",
            files_in_diff=parse_diff(TWO_HUNK_DIFF),
            budgets=ContextBudgets(diff_hunks=diff_hunks, surrounding_context=50_000),
            packaging=ContextPackagingConfig(partial_review_mode_enabled=False),
        )
    )


def test_rank_hunk_candidates_sorts_by_score_desc_with_stable_file_line_ties() -> None:
    file_in_diff = parse_diff(TWO_HUNK_DIFF)[0]

    def candidate(file_index: int, hunk_index: int, score: float) -> HunkCandidate:
        return HunkCandidate(
            file_index=file_index,
            hunk_index=hunk_index,
            file_in_diff=file_in_diff,
            hunk=[],
            score=score,
        )

    ranked = rank_hunk_candidates(
        [candidate(0, 1, 2.0), candidate(1, 1, 9.0), candidate(0, 2, 2.0), candidate(0, 3, 5.0)]
    )

    assert [(c.file_index, c.hunk_index) for c in ranked] == [(1, 1), (0, 3), (0, 1), (0, 2)]


def test_build_context_bundle_budget_goes_to_highest_risk_hunk_first() -> None:
    full = _two_hunk_bundle(diff_hunks=10_000)
    hunk_tokens = {
        segment.source_id: segment.token_count
        for segment in full.package.review
        if ":hunk:" in segment.source_id
    }
    assert set(hunk_tokens) == {"app.py:hunk:1", "app.py:hunk:2"}
    # Hunk 2 adds more lines, so it scores higher and is also the larger one.
    assert hunk_tokens["app.py:hunk:2"] > hunk_tokens["app.py:hunk:1"]

    tight = _two_hunk_bundle(diff_hunks=hunk_tokens["app.py:hunk:2"])

    kept = [s.source_id for s in tight.package.review if ":hunk:" in s.source_id]
    assert kept == ["app.py:hunk:2"]
    assert "app.py:hunk:1" in tight.package.dropped_segments


def test_build_context_bundle_renders_selected_hunks_in_file_line_order() -> None:
    bundle = _two_hunk_bundle(diff_hunks=10_000)

    ids = [segment.source_id for segment in bundle.package.review]

    assert ids == [
        "app.py:hunk:1",
        "app.py:context:1",
        "app.py:hunk:2",
        "app.py:context:2",
    ]
    assert bundle.rendered.index("Hunk 1 (around line 10)") < bundle.rendered.index(
        "Hunk 2 (around line 100)"
    )


def test_fetch_sources_concurrently_bounds_parallelism_and_preserves_order() -> None:
    class SlowClient:
        def __init__(self) -> None:
            self.in_flight = 0
            self.max_in_flight = 0

        async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            await asyncio.sleep(0.01)
            self.in_flight -= 1
            return f"content of {path}"

    diff_text = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        for i in range(20)
    )
    files = parse_diff(diff_text)
    client = SlowClient()

    sources = asyncio.run(fetch_sources_concurrently(client, "acme", "demo", "sha", files))

    assert sources == [f"content of f{i}.py" for i in range(20)]
    assert 1 < client.max_in_flight <= 8