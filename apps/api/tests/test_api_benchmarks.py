"""Tests for the /api/v1/benchmarks and /api/v1/telemetry endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.benchmarks import router as benchmarks_router, telemetry_router, _verify_api_access
from app.config import settings
from app.db.models import BenchmarkResult, BenchmarkRun, FindingOutcome, Installation, Review
from app.db.session import AsyncSessionLocal, engine, set_installation_context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _rand_id() -> int:
    return int(str(uuid4().int)[:9])


@pytest.fixture(autouse=True)
async def reset_db_pool() -> None:
    await engine.dispose()


def _auth_headers() -> dict[str, str]:
    if settings.api_access_key:
        return {"X-Api-Key": settings.api_access_key}
    return {}


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(benchmarks_router)
    application.include_router(telemetry_router)
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> httpx.AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _seed_benchmark_run(name: str = "test-run") -> int:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        run = BenchmarkRun(
            name=name,
            prompt_version="v1",
            model_config_json={"model": "claude-sonnet-4-5"},
            dataset_path="evals/datasets",
            triggered_by="ci",
            status="completed",
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.flush()
        run_id = int(run.id)
        await session.commit()
    return run_id


async def _seed_benchmark_result(run_id: int) -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        result = BenchmarkResult(
            run_id=run_id,
            case_id="security_001",
            review_id=None,
            expected_findings=1,
            predicted_findings=1,
            true_positives=1,
            false_positives=0,
            false_negatives=0,
            total_tokens=500,
            cost_usd=Decimal("0.01"),
        )
        session.add(result)
        await session.commit()


async def _seed_installation_and_review() -> tuple[int, int]:
    installation_id = _rand_id()
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"test-{installation_id}",
                account_type="Organization",
            )
        )
        await session.flush()
        review = Review(
            installation_id=installation_id,
            repo_full_name="acme/bench-repo",
            pr_number=1,
            pr_head_sha="a" * 40,
            status="done",
            model_provider="anthropic",
            model="claude-sonnet-4-5",
            findings={"findings": [{"severity": "high", "category": "security"}]},
            debug_artifacts={},
            tokens_used=100,
            cost_usd=Decimal("0.05"),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(review)
        await session.flush()
        review_id = int(review.id)
        # Add a true positive finding outcome
        session.add(
            FindingOutcome(
                review_id=review_id,
                finding_index=0,
                github_comment_id=1001,
                outcome="applied_directly",
                outcome_confidence="high",
                signals={},
            )
        )
        await session.commit()
    return installation_id, review_id


# ---------------------------------------------------------------------------
# _verify_api_access
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_benchmarks_verify_api_access_production_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "api_access_key", None)
    with pytest.raises(HTTPException) as exc_info:
        _verify_api_access(None)
    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# list_benchmark_runs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_benchmark_runs_empty(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.get("/api/v1/benchmarks/runs", headers=_auth_headers())
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_list_benchmark_runs_returns_runs(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    run_id = await _seed_benchmark_run("my-bench")

    resp = await client.get("/api/v1/benchmarks/runs", headers=_auth_headers())
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert run_id in ids


# ---------------------------------------------------------------------------
# get_benchmark_run
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_benchmark_run_not_found(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.get("/api/v1/benchmarks/runs/99999999", headers=_auth_headers())
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_benchmark_run_with_results(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    run_id = await _seed_benchmark_run("full-run")
    await _seed_benchmark_result(run_id)

    resp = await client.get(f"/api/v1/benchmarks/runs/{run_id}", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == run_id
    assert body["name"] == "full-run"
    assert len(body["cases"]) == 1
    case = body["cases"][0]
    assert case["case_id"] == "security_001"
    assert case["true_positives"] == 1
    assert case["precision"] == pytest.approx(1.0)
    assert case["recall"] == pytest.approx(1.0)


@pytest.mark.anyio
async def test_get_benchmark_run_precision_recall_none_when_no_tp(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    run_id = await _seed_benchmark_run("zero-run")
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        result = BenchmarkResult(
            run_id=run_id,
            case_id="fp_case",
            expected_findings=0,
            predicted_findings=1,
            true_positives=0,
            false_positives=1,
            false_negatives=0,
        )
        session.add(result)
        await session.commit()

    resp = await client.get(f"/api/v1/benchmarks/runs/{run_id}", headers=_auth_headers())
    assert resp.status_code == 200
    case = resp.json()["cases"][0]
    assert case["precision"] == pytest.approx(0.0)  # 0/(0+1) = 0.0
    assert case["recall"] is None  # 0/(0+0): denominator=0, returns None


# ---------------------------------------------------------------------------
# compare_benchmark_runs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compare_benchmark_runs_not_found(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.get(
        "/api/v1/benchmarks/compare?run_a=99998&run_b=99999", headers=_auth_headers()
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_compare_benchmark_runs_returns_delta(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    run_a = await _seed_benchmark_run("run-a")
    run_b = await _seed_benchmark_run("run-b")

    await engine.dispose()
    async with AsyncSessionLocal() as session:
        run_a_row = await session.get(BenchmarkRun, run_a)
        run_b_row = await session.get(BenchmarkRun, run_b)
        assert run_a_row is not None and run_b_row is not None
        run_a_row.totals_json = {"precision": 0.9, "recall": 0.8}
        run_b_row.totals_json = {"precision": 0.8, "recall": 0.7}
        await session.commit()

    resp = await client.get(
        f"/api/v1/benchmarks/compare?run_a={run_a}&run_b={run_b}", headers=_auth_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_a"]["id"] == run_a
    assert body["run_b"]["id"] == run_b
    assert body["delta"]["precision"] == pytest.approx(0.1)
    assert body["delta"]["recall"] == pytest.approx(0.1)


@pytest.mark.anyio
async def test_compare_benchmark_runs_delta_none_for_missing_totals(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    run_a = await _seed_benchmark_run("run-a-null")
    run_b = await _seed_benchmark_run("run-b-null")
    # Leave totals_json as None

    resp = await client.get(
        f"/api/v1/benchmarks/compare?run_a={run_a}&run_b={run_b}", headers=_auth_headers()
    )
    assert resp.status_code == 200
    assert resp.json()["delta"]["precision"] is None


# ---------------------------------------------------------------------------
# cost_per_finding
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cost_per_finding_empty(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    # Filter by a non-existent installation_id so accumulated test data doesn't bleed in
    empty_installation_id = _rand_id()
    resp = await client.get(
        f"/api/v1/telemetry/cost-per-finding?installation_id={empty_installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total_true_positives"] == 0
    assert body["summary"]["overall_cost_per_tp_usd"] is None


@pytest.mark.anyio
async def test_cost_per_finding_with_data(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id, review_id = await _seed_installation_and_review()

    resp = await client.get(
        f"/api/v1/telemetry/cost-per-finding?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total_true_positives"] >= 1
    assert body["summary"]["overall_cost_per_tp_usd"] is not None


@pytest.mark.anyio
async def test_cost_per_finding_model_filter(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id, _ = await _seed_installation_and_review()

    resp = await client.get(
        f"/api/v1/telemetry/cost-per-finding?installation_id={installation_id}&model=nonexistent-model",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["summary"]["reviews_analyzed"] == 0
