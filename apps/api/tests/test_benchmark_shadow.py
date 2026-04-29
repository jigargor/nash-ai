from types import SimpleNamespace

import pytest

from app.agent.benchmark_shadow import _finding_overlap, should_enqueue_shadow_benchmark


def test_should_enqueue_shadow_benchmark_honors_sample_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agent.benchmark_shadow.settings.review_benchmark_sample_rate", 0.0)
    assert should_enqueue_shadow_benchmark(123) is False

    monkeypatch.setattr("app.agent.benchmark_shadow.settings.review_benchmark_sample_rate", 1.0)
    assert should_enqueue_shadow_benchmark(123) is True


def test_finding_overlap_computes_intersection_ratio() -> None:
    control = [
        SimpleNamespace(file_path="a.py", line_start=10, severity="high", category="security"),
        SimpleNamespace(file_path="b.py", line_start=5, severity="medium", category="correctness"),
    ]
    candidate = [
        SimpleNamespace(file_path="a.py", line_start=10, severity="high", category="security"),
        SimpleNamespace(file_path="c.py", line_start=7, severity="low", category="style"),
    ]

    assert _finding_overlap(control, candidate) == 0.5
