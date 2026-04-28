from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from app.agent.offline_eval import replay_case_directory_to_review_result
from .overlap_metric import FindingOverlapMetric

deepeval_module = pytest.importorskip("deepeval")
if not hasattr(deepeval_module, "assert_test"):
    pytest.skip("deepeval is installed without assert_test export", allow_module_level=True)
assert_test = deepeval_module.assert_test
try:
    from deepeval.test_case import LLMTestCase
except Exception:  # pragma: no cover - import availability depends on local deepeval install
    pytest.skip("deepeval test_case module unavailable", allow_module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _dataset_cases() -> list[Path]:
    datasets_root = REPO_ROOT / "evals" / "datasets"
    return sorted(path for path in datasets_root.iterdir() if path.is_dir() and (path / "expected.json").exists())


def _as_prediction_payload(review_result: Any) -> dict[str, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    for finding in review_result.findings:
        findings.append(
            {
                "severity": finding.severity,
                "category": finding.category,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
            }
        )
    return {"findings": findings}


def test_deepeval_metric_smoke() -> None:
    test_case = LLMTestCase(
        input="offline-smoke",
        expected_output=json.dumps(
            {
                "findings": [
                    {
                        "severity": "high",
                        "category": "security",
                        "file_path": "src/main.py",
                        "line_start": 10,
                    }
                ]
            }
        ),
        actual_output=json.dumps(
            {
                "findings": [
                    {
                        "severity": "critical",
                        "category": "security",
                        "file_path": "src/main.py",
                        "line_start": 11,
                    }
                ]
            }
        ),
    )
    assert_test(test_case=test_case, metrics=[FindingOverlapMetric(threshold=0.5)], run_async=False)


@pytest.mark.live_llm
@pytest.mark.parametrize("case_dir", _dataset_cases(), ids=lambda p: p.name)
def test_deepeval_live_agent_replay(case_dir: Path) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set")
    expected_payload = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    review_result = asyncio.run(replay_case_directory_to_review_result(case_dir))
    predicted_payload = _as_prediction_payload(review_result)
    test_case = LLMTestCase(
        input=case_dir.name,
        expected_output=json.dumps(expected_payload),
        actual_output=json.dumps(predicted_payload),
    )
    assert_test(test_case=test_case, metrics=[FindingOverlapMetric(threshold=0.2)], run_async=False)
