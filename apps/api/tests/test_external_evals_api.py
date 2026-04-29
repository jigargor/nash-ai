"""HTTP route tests for app.api.external_evals (estimate, create, list, get, cancel)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.agent.external.github_public import PublicRepoError
from app.api import external_evals as external_evals_api
from app.config import settings
from app.db.models import (
    ExternalEvaluation,
    ExternalEvaluationFinding,
    ExternalEvaluationShard,
    User,
)
from app.db.session import AsyncSessionLocal, set_installation_context
from conftest import (
    _FakeRedis,
    _TEST_DASHBOARD_USER_GITHUB_ID,
    _auth_headers,
    _insert_installation,
    _random_installation_id,
)


def _preflight_result(
    *,
    estimated_tokens: int = 10_000,
    estimated_cost: Decimal | None = None,
) -> external_evals_api._PreflightResult:
    cost = estimated_cost if estimated_cost is not None else Decimal("0.01")
    return external_evals_api._PreflightResult(
        owner="acme",
        repo="demo",
        target_ref="main",
        default_branch="main",
        file_count=3,
        total_bytes=9000,
        estimated_tokens=estimated_tokens,
        estimated_cost_usd=cost,
    )


@pytest.fixture
def ee_app() -> FastAPI:
    application = FastAPI()
    application.state.redis = _FakeRedis()
    application.include_router(external_evals_api.router)
    return application


@pytest.fixture(autouse=True)
def _configure_dashboard_and_clear_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dashboard_user_jwt_secret", "test-dashboard-user-secret")
    monkeypatch.setattr(settings, "dashboard_user_jwt_audience", "dashboard-api")
    monkeypatch.setattr(settings, "dashboard_user_jwt_issuer", "nash-web-dashboard")
    external_evals_api._preflight_cache.clear()


@pytest.fixture
async def ee_client(ee_app: FastAPI) -> httpx.AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=ee_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _dashboard_user_pk() -> int:
    async with AsyncSessionLocal() as session:
        user_id = await session.scalar(
            select(User.id).where(User.github_id == _TEST_DASHBOARD_USER_GITHUB_ID).limit(1)
        )
    assert user_id is not None
    return int(user_id)


@pytest.mark.anyio
async def test_estimate_returns_preflight_summary(
    ee_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def fake_preflight(*_a: object, **_k: object) -> external_evals_api._PreflightResult:
        return _preflight_result()

    monkeypatch.setattr(external_evals_api, "_resolve_preflight", fake_preflight)

    resp = await ee_client.post(
        "/api/v1/external-evals/estimate",
        json={"installation_id": installation_id, "repo_url": "https://github.com/acme/demo"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner"] == "acme"
    assert body["estimated_tokens"] == 10_000
    assert body["ack_required"] is True


@pytest.mark.anyio
async def test_estimate_public_repo_error_returns_400(
    ee_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def boom(*_a: object, **_k: object) -> None:
        raise PublicRepoError("unsupported URL")

    monkeypatch.setattr(external_evals_api, "_resolve_preflight", boom)

    resp = await ee_client.post(
        "/api/v1/external-evals/estimate",
        json={"installation_id": installation_id, "repo_url": "bad"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_create_requires_ack_confirmation(
    ee_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    resp = await ee_client.post(
        "/api/v1/external-evals",
        json={
            "installation_id": installation_id,
            "repo_url": "https://github.com/acme/demo",
            "ack_confirmed": False,
            "token_budget_cap": 2_000_000,
            "cost_budget_cap_usd": 500.0,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_create_rejects_budget_below_estimate(
    ee_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def fake_preflight(*_a: object, **_k: object) -> external_evals_api._PreflightResult:
        return _preflight_result(estimated_tokens=999_999, estimated_cost=Decimal("5.000000"))

    monkeypatch.setattr(external_evals_api, "_resolve_preflight", fake_preflight)

    resp_low_tokens = await ee_client.post(
        "/api/v1/external-evals",
        json={
            "installation_id": installation_id,
            "repo_url": "https://github.com/acme/demo",
            "ack_confirmed": True,
            "token_budget_cap": 500_000,
            "cost_budget_cap_usd": 500.0,
        },
        headers=_auth_headers(),
    )
    assert resp_low_tokens.status_code == 400

    async def fake_preflight_high_cost(*_a: object, **_k: object) -> external_evals_api._PreflightResult:
        return _preflight_result(
            estimated_tokens=10_000, estimated_cost=Decimal("10.500000")
        )

    monkeypatch.setattr(external_evals_api, "_resolve_preflight", fake_preflight_high_cost)

    resp_low_cost = await ee_client.post(
        "/api/v1/external-evals",
        json={
            "installation_id": installation_id,
            "repo_url": "https://github.com/acme/demo",
            "ack_confirmed": True,
            "token_budget_cap": 2_000_000,
            "cost_budget_cap_usd": 5.0,
        },
        headers=_auth_headers(),
    )
    assert resp_low_cost.status_code == 400


@pytest.mark.anyio
async def test_create_queues_job_and_returns_eval_id(
    ee_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def fake_preflight(*_a: object, **_k: object) -> external_evals_api._PreflightResult:
        return _preflight_result(estimated_tokens=8_000, estimated_cost=Decimal("0.000500"))

    monkeypatch.setattr(external_evals_api, "_resolve_preflight", fake_preflight)

    resp = await ee_client.post(
        "/api/v1/external-evals",
        json={
            "installation_id": installation_id,
            "repo_url": " https://GITHUB.com/AcMe/Demo ",
            "ack_confirmed": True,
            "token_budget_cap": 2_000_000,
            "cost_budget_cap_usd": 500.0,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "queued"
    assert isinstance(body["external_eval_id"], int)


@pytest.mark.anyio
async def test_list_and_get_external_eval_round_trip(
    ee_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    user_pk = await _dashboard_user_pk()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        ev = ExternalEvaluation(
            installation_id=installation_id,
            requested_by_user_id=user_pk,
            repo_url="https://github.com/acme/demo",
            owner="acme",
            repo="demo",
            target_ref="main",
            status="complete",
            estimated_tokens=100,
            estimated_cost_usd=0.01,
            token_budget_cap=1_000_000,
            cost_budget_cap_usd=float(Decimal("5")),
            ack_required=True,
            ack_confirmed=True,
            summary="Done",
            created_at=now,
            updated_at=now,
        )
        session.add(ev)
        await session.flush()
        eval_id = int(ev.id)
        session.add(
            ExternalEvaluationShard(
                external_evaluation_id=eval_id,
                installation_id=installation_id,
                shard_key="a",
                status="done",
                model_tier="economy",
                file_count=2,
                findings_count=0,
                tokens_used=0,
                cost_usd=0.0,
            )
        )
        session.add(
            ExternalEvaluationFinding(
                external_evaluation_id=eval_id,
                installation_id=installation_id,
                category="bug",
                severity="high",
                title="Leak",
                message="oops",
                file_path="main.py",
                line_start=1,
                line_end=2,
                evidence={},
            )
        )
        await session.commit()

    list_resp = await ee_client.get(
        f"/api/v1/external-evals?installation_id={installation_id}&limit=5",
        headers=_auth_headers(),
    )
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert listed[0]["id"] == eval_id

    get_resp = await ee_client.get(
        f"/api/v1/external-evals/{eval_id}?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["findings"][0]["title"] == "Leak"
    assert detail["shards"][0]["shard_key"] == "a"

    missing = await ee_client.get(
        f"/api/v1/external-evals/999999999?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_cancel_terminal_eval_returns_prior_status_without_mutation(
    ee_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    user_pk = await _dashboard_user_pk()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        ev = ExternalEvaluation(
            installation_id=installation_id,
            requested_by_user_id=user_pk,
            repo_url="https://github.com/acme/old",
            owner="acme",
            repo="old",
            target_ref="main",
            status="failed",
            estimated_tokens=1,
            estimated_cost_usd=0.001,
            token_budget_cap=1_000_000,
            cost_budget_cap_usd=float(Decimal("1")),
            ack_required=False,
            ack_confirmed=True,
            summary="failed run",
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
        session.add(ev)
        await session.flush()
        eval_id = int(ev.id)
        await session.commit()

    resp = await ee_client.post(
        f"/api/v1/external-evals/{eval_id}/cancel",
        json={"installation_id": installation_id},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


@pytest.mark.anyio
async def test_cancel_marks_running_eval_as_canceled(
    ee_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    user_pk = await _dashboard_user_pk()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        ev = ExternalEvaluation(
            installation_id=installation_id,
            requested_by_user_id=user_pk,
            repo_url="https://github.com/acme/live",
            owner="acme",
            repo="live",
            target_ref="main",
            status="queued",
            estimated_tokens=1,
            estimated_cost_usd=0.001,
            token_budget_cap=1_000_000,
            cost_budget_cap_usd=float(Decimal("1")),
            ack_required=False,
            ack_confirmed=True,
            summary=None,
            created_at=now,
            updated_at=now,
        )
        session.add(ev)
        await session.flush()
        eval_id = int(ev.id)
        await session.commit()

    resp = await ee_client.post(
        f"/api/v1/external-evals/{eval_id}/cancel",
        json={"installation_id": installation_id},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "canceled"

    get_resp = await ee_client.get(
        f"/api/v1/external-evals/{eval_id}?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert get_resp.json()["status"] == "canceled"




def test_preflight_cache_key_normalizes_repo_url_and_ref() -> None:
    k1 = external_evals_api._preflight_cache_key(7, "https://Github.com/acme/repo", None)
    k2 = external_evals_api._preflight_cache_key(7, "  https://github.com/acme/repo  ", None)
    assert k1 == k2
    k3 = external_evals_api._preflight_cache_key(7, "https://github.com/acme/repo", "  main  ")
    k4 = external_evals_api._preflight_cache_key(7, "https://github.com/acme/repo", "main")
    assert k3 == k4
