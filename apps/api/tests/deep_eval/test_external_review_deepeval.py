from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.mcp.context import MCPToolContext
from app.mcp.tools.estimate_review import EstimateReviewRequest, estimate_review_tool
from app.mcp.tools.review_repository import ReviewRepositoryRequest, review_repository_tool
from app.review.external import EngineConfig, InMemoryRepoSource
from app.review.external.models import Finding

deepeval_module = pytest.importorskip("deepeval")
if not hasattr(deepeval_module, "assert_test"):
    pytest.skip("deepeval is installed without assert_test export", allow_module_level=True)
assert_test = deepeval_module.assert_test
try:
    from deepeval.test_case import LLMTestCase
except Exception:  # pragma: no cover - depends on local deepeval package availability
    pytest.skip("deepeval test_case module unavailable", allow_module_level=True)


def _external_review_dataset_cases() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[4]
    datasets_root = repo_root / "evals" / "datasets"
    return sorted(
        case_dir
        for case_dir in datasets_root.iterdir()
        if case_dir.is_dir()
        and case_dir.name.startswith("external_review_")
        and (case_dir / "context.json").exists()
        and (case_dir / "expected.json").exists()
    )


def _as_prediction_payload(
    findings: list[Finding],
) -> dict[str, list[dict[str, str | int]]]:
    payload: list[dict[str, str | int]] = []
    for finding in findings:
        payload.append(
            {
                "severity": str(finding.severity),
                "category": str(finding.category),
                "file_path": str(finding.file_path),
                "line_start": int(finding.line_start),
            }
        )
    return {"findings": payload}


def _build_ctx_from_dataset(case_dir: Path) -> tuple[MCPToolContext, str]:
    context_payload = json.loads((case_dir / "context.json").read_text(encoding="utf-8"))
    repo_value = str(context_payload.get("repo") or "offline/offline").strip()
    if "/" in repo_value:
        owner, repo = repo_value.split("/", 1)
    else:
        owner, repo = "offline", repo_value
    owner = owner or "offline"
    repo = repo or "offline"
    files_raw = context_payload.get("files", {})
    files: dict[str, str] = {}
    if isinstance(files_raw, dict):
        for path, content in files_raw.items():
            if isinstance(path, str) and isinstance(content, str):
                files[path.replace("\\", "/")] = content
    source = InMemoryRepoSource(
        owner=owner,
        repo=repo,
        default_branch="main",
        refs={"main": files},
    )
    return (
        MCPToolContext(source=source, config=EngineConfig(prepass_sample_limit=50)),
        f"https://github.com/{owner}/{repo}",
    )


@pytest.mark.anyio
async def test_deepeval_external_review_pipeline_offline() -> None:
    from .overlap_metric import FindingOverlapMetric

    files = {
        "src/auth.py": "def run(user_input):\n    eval(user_input)\n",
        "src/utils.py": "def ok():\n    return 1\n",
        "README.md": "safe docs",
    }
    source = InMemoryRepoSource(
        owner="octocat",
        repo="repo",
        default_branch="main",
        refs={"main": files},
    )
    ctx = MCPToolContext(
        source=source,
        config=EngineConfig(prepass_sample_limit=20),
    )
    try:
        estimate = await estimate_review_tool(
            EstimateReviewRequest(repo_url="https://github.com/octocat/repo"),
            ctx=ctx,
        )
        assert estimate.ok
        review_result = await review_repository_tool(
            ReviewRepositoryRequest(
                repo_url="https://github.com/octocat/repo",
                ack_token=estimate.ack_token,
            ),
            ctx=ctx,
        )
        assert review_result.ok
        assert review_result.report is not None
        predicted_payload = _as_prediction_payload(review_result.report.findings)
        expected_payload = {
            "findings": [
                {
                    "severity": "high",
                    "category": "security",
                    "file_path": "src/auth.py",
                    "line_start": 2,
                }
            ]
        }
        test_case = LLMTestCase(
            input="external-review-offline-case",
            expected_output=json.dumps(expected_payload),
            actual_output=json.dumps(predicted_payload),
        )
        assert_test(
            test_case=test_case,
            metrics=[FindingOverlapMetric(threshold=0.8)],
            run_async=False,
        )
    finally:
        await ctx.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("case_dir", _external_review_dataset_cases(), ids=lambda p: p.name)
async def test_deepeval_external_review_datasets(case_dir: Path) -> None:
    from .overlap_metric import FindingOverlapMetric

    expected_payload = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    expected_findings = list(expected_payload.get("findings", []))
    ctx, repo_url = _build_ctx_from_dataset(case_dir)
    try:
        estimate = await estimate_review_tool(
            EstimateReviewRequest(repo_url=repo_url),
            ctx=ctx,
        )
        assert estimate.ok
        review_result = await review_repository_tool(
            ReviewRepositoryRequest(repo_url=repo_url, ack_token=estimate.ack_token),
            ctx=ctx,
        )
        assert review_result.ok
        assert review_result.report is not None
        predicted_payload = _as_prediction_payload(review_result.report.findings)
        if not expected_findings:
            assert (
                predicted_payload["findings"] == []
            ), f"{case_dir.name} should not return any findings"
            return

        test_case = LLMTestCase(
            input=case_dir.name,
            expected_output=json.dumps(expected_payload),
            actual_output=json.dumps(predicted_payload),
        )
        assert_test(
            test_case=test_case,
            metrics=[FindingOverlapMetric(threshold=0.6)],
            run_async=False,
        )
    finally:
        await ctx.aclose()
