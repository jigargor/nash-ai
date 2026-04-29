from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import delete, select

from app.api.auth import CurrentDashboardUser
from app.api import usage as usage_router
from app.config import settings
from app.db.models import (
    ApiUsageEvent,
    Installation,
    Review,
    ReviewModelAudit,
    User,
    UserProviderKey,
)
from app.db.session import AsyncSessionLocal, engine, set_installation_context

from conftest import (
    _TEST_DASHBOARD_USER_GITHUB_ID,
    _TEST_DASHBOARD_USER_LOGIN,
    _auth_headers,
    _dashboard_user_token,
    _insert_installation,
    _insert_review,
    _random_installation_id,
)


@pytest.fixture(autouse=True)
def _configure_dashboard_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dashboard_user_jwt_secret", "test-dashboard-user-secret")
    monkeypatch.setattr(settings, "dashboard_user_jwt_audience", "dashboard-api")
    monkeypatch.setattr(settings, "dashboard_user_jwt_issuer", "nash-web-dashboard")


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(usage_router.router)
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.mark.anyio
async def test_usage_summary_uses_stage_provider_usage_for_api_key_caps(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add_all(
            [
                ReviewModelAudit(
                    review_id=review_id,
                    installation_id=installation_id,
                    run_id="run-usage",
                    stage="fast_path",
                    provider="gemini",
                    model="gemini-2.5-flash-lite",
                    input_tokens=100,
                    output_tokens=10,
                    total_tokens=110,
                ),
                ReviewModelAudit(
                    review_id=review_id,
                    installation_id=installation_id,
                    run_id="run-usage",
                    stage="primary",
                    provider="openai",
                    model="gpt-5.5",
                    input_tokens=200,
                    output_tokens=50,
                    total_tokens=250,
                ),
            ]
        )
        await session.commit()

    response = await client.get(
        f"/api/v1/usage/summary?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 200

    payload = response.json()
    providers = {row["provider"] for row in payload["api_key_caps"]}
    assert "gemini" in providers
    assert "openai" in providers


@pytest.mark.anyio
async def test_usage_summary_reports_activity_and_capped_budget(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    monkeypatch.setattr(settings, "daily_token_budget_per_installation", 100)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id)
    now = datetime.now(timezone.utc)

    provider_name = "openai"

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        user_id = await session.scalar(select(User.id).where(User.github_id == 999001))
        assert user_id is not None
        await session.execute(
            delete(UserProviderKey).where(
                UserProviderKey.user_id == int(user_id),
                UserProviderKey.provider == provider_name,
            )
        )
        session.add(
            ApiUsageEvent(
                installation_id=installation_id,
                service="github",
                endpoint="/repos/acme/repo",
                method="GET",
                status_code=200,
                occurred_at=now,
            )
        )
        session.add(
            UserProviderKey(user_id=int(user_id), provider=provider_name, key_enc=b"encrypted")
        )
        session.add(
            ReviewModelAudit(
                review_id=review_id,
                installation_id=installation_id,
                run_id="run-usage-capped",
                stage="primary",
                provider="anthropic",
                model="claude-sonnet-4-5",
                input_tokens=50,
                output_tokens=10,
                total_tokens=60,
                created_at=now,
            )
        )
        await session.commit()

    response = await client.get(
        f"/api/v1/usage/summary?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["service_breakdown"] == [{"service": "github", "requests": 1}]
    assert payload["daily_requests"][0]["requests"] == 1
    assert payload["weekly_requests"][0]["requests"] == 1
    assert provider_name in payload["configured_providers"]
    assert payload["configured_provider_count"] >= 1
    assert payload["cumulative_caps"]["state"] == "capped"
    assert payload["session_cap"]["remaining"] == 0


def test_verify_api_access_allows_when_key_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", None)

    usage_router._verify_api_access(None)


def test_verify_api_access_rejects_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "secret")

    with pytest.raises(HTTPException) as exc_info:
        usage_router._verify_api_access("wrong")

    assert exc_info.value.status_code == 401


def test_require_installation_access_returns_404_for_unlinked_installation() -> None:
    with pytest.raises(HTTPException) as exc_info:
        usage_router._require_installation_access({1, 2}, 3)

    assert exc_info.value.status_code == 404


async def _insert_orphan_installation(installation_id: int) -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"orphan-{installation_id}",
                account_type="Organization",
            )
        )
        await session.commit()


@pytest.mark.anyio
async def test_usage_summary_returns_404_for_installation_not_linked_to_user(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_orphan_installation(installation_id)

    response = await client.get(
        f"/api/v1/usage/summary?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Installation not found"


@pytest.mark.anyio
async def test_usage_summary_reports_near_cap_state(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    monkeypatch.setattr(settings, "daily_token_budget_per_installation", 10_000)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Review(
                installation_id=installation_id,
                repo_full_name="acme/usage-near",
                pr_number=11,
                pr_head_sha="b" * 40,
                status="done",
                model_provider="anthropic",
                model="claude-sonnet-4-5",
                tokens_used=8_500,
                cost_usd=1.5,
            )
        )
        await session.commit()

    response = await client.get(
        f"/api/v1/usage/summary?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["cumulative_caps"]["state"] == "near-cap"
    assert payload["session_cap"]["state"] == "near-cap"
    assert payload["cumulative_caps"]["daily_token_budget"] == 10_000


@pytest.mark.anyio
async def test_usage_summary_merges_weekly_only_provider_into_api_key_caps(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id, pr_number=99)
    older = datetime.now(timezone.utc) - timedelta(days=3)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            ReviewModelAudit(
                review_id=review_id,
                installation_id=installation_id,
                run_id="run-weekly-only",
                stage="primary",
                provider="provider_weekly_only",
                model="some-model",
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                created_at=older,
            )
        )
        await session.commit()

    response = await client.get(
        f"/api/v1/usage/summary?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    caps = {row["provider"]: row for row in response.json()["api_key_caps"]}
    row = caps["provider_weekly_only"]
    assert row["daily_tokens"] == 0
    assert row["weekly_tokens"] == 15
    assert float(row["weekly_cost_usd"]) >= 0


@pytest.mark.anyio
async def test_usage_summary_accepts_configured_api_access_key(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "usage-test-api-key")
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    missing = await client.get(
        f"/api/v1/usage/summary?installation_id={installation_id}",
        headers={"X-Dashboard-User-Token": _dashboard_user_token()},
    )
    assert missing.status_code == 401

    ok = await client.get(
        f"/api/v1/usage/summary?installation_id={installation_id}",
        headers={
            "X-Dashboard-User-Token": _dashboard_user_token(),
            "X-Api-Key": "usage-test-api-key",
        },
    )
    assert ok.status_code == 200
    assert ok.json()["installation_id"] == installation_id


@pytest.mark.anyio
async def test_allowed_installation_ids_includes_linked_dashboard_installations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    ids = await usage_router._allowed_installation_ids(
        CurrentDashboardUser(github_id=_TEST_DASHBOARD_USER_GITHUB_ID, login=_TEST_DASHBOARD_USER_LOGIN),
    )
    assert installation_id in ids


@pytest.mark.anyio
async def test_get_usage_summary_direct_call_returns_full_summary_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise `get_usage_summary` in-process so coverage attributes the handler body."""
    monkeypatch.setattr(settings, "api_access_key", None)
    monkeypatch.setattr(settings, "daily_token_budget_per_installation", 50_000)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        now = datetime.now(timezone.utc)
        session.add(
            ReviewModelAudit(
                review_id=review_id,
                installation_id=installation_id,
                run_id="r-direct-caps",
                stage="primary",
                provider="anthropic",
                model="claude-sonnet-4-5",
                input_tokens=20,
                output_tokens=10,
                total_tokens=42,
                created_at=now,
            )
        )
        await session.commit()

    result = cast(
        dict[str, Any],
        await usage_router.get_usage_summary(
            installation_id=installation_id,
            current_user=CurrentDashboardUser(
                github_id=_TEST_DASHBOARD_USER_GITHUB_ID,
                login=_TEST_DASHBOARD_USER_LOGIN,
            ),
        ),
    )
    assert result["installation_id"] == installation_id
    assert "service_breakdown" in result
    tu = result["token_usage"]
    assert int(tu["daily"]) >= 0 and int(tu["weekly"]) >= 0
    assert isinstance(result["configured_providers"], list)
    assert result["cumulative_caps"]["state"] in {"safe", "near-cap", "capped"}
    cap_rows = {row["provider"]: row for row in result["api_key_caps"]}
    assert cap_rows["anthropic"]["weekly_tokens"] >= 42
    assert cap_rows["anthropic"]["daily_tokens"] >= 42


@pytest.mark.anyio
async def test_get_usage_summary_direct_call_cap_state_near_and_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)

    installation_id_near = _random_installation_id()
    await _insert_installation(installation_id_near)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id_near)
        session.add(
            Review(
                installation_id=installation_id_near,
                repo_full_name="acme/near",
                pr_number=501,
                pr_head_sha="c" * 40,
                status="done",
                model_provider="anthropic",
                model="claude-sonnet-4-5",
                tokens_used=820,
                cost_usd=1.0,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "daily_token_budget_per_installation", 1_000)
    near_payload = cast(
        dict[str, Any],
        await usage_router.get_usage_summary(
            installation_id=installation_id_near,
            current_user=CurrentDashboardUser(
                github_id=_TEST_DASHBOARD_USER_GITHUB_ID,
                login=_TEST_DASHBOARD_USER_LOGIN,
            ),
        ),
    )
    assert near_payload["cumulative_caps"]["state"] == "near-cap"

    installation_id_capped = _random_installation_id()
    await _insert_installation(installation_id_capped)
    await _insert_review(installation_id_capped)

    monkeypatch.setattr(settings, "daily_token_budget_per_installation", 100)
    capped_payload = cast(
        dict[str, Any],
        await usage_router.get_usage_summary(
            installation_id=installation_id_capped,
            current_user=CurrentDashboardUser(
                github_id=_TEST_DASHBOARD_USER_GITHUB_ID,
                login=_TEST_DASHBOARD_USER_LOGIN,
            ),
        ),
    )
    assert capped_payload["cumulative_caps"]["state"] == "capped"
