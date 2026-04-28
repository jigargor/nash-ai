from __future__ import annotations

from pathlib import Path

from app.agent.offline_eval import replay_case_directory_to_review_result


def test_dataset_cases_exist_for_deepeval_harness() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    datasets_root = repo_root / "evals" / "datasets"
    cases = [path for path in datasets_root.iterdir() if path.is_dir() and (path / "expected.json").exists()]
    assert cases, "expected at least one eval dataset case"


def test_replay_function_is_importable() -> None:
    assert callable(replay_case_directory_to_review_result)
