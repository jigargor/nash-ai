from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.api import usage_metrics
from app.config import settings
from app.db.models import ReviewModelAudit
from app.db.session import AsyncSessionLocal, set_installation_context
from conftest import _auth_headers, _insert_installation, _insert_review, _random_installation_id


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    async def _fake_current_user() -> CurrentDashboardUser:
        return CurrentDashboardUser(github_id=20483022, login="tester")

    application.dependency_overrides[get_current_dashboard_user] = _fake_current_user
    application.include_router(usage_metrics.router)
    return application


@pytest.fixture(autouse=True)
def _configure_dashboard_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dashboard_user_jwt_secret", "test-dashboard-user-secret")
    monkeypatch.setattr(settings, "dashboard_user_jwt_audience", "dashboard-api")
    monkeypatch.setattr(settings, "dashboard_user_jwt_issuer", "nash-web-dashboard")


@pytest.fixture
async def client(test_app: FastAPI) -> httpx.AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.mark.anyio
async def test_usage_metrics_returns_provider_rows_and_redacts_metadata(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id, repo_full_name="acme/repo")
    now = datetime.now(timezone.utc)
    async def _fake_allowed_installation_ids(*_args: object, **_kwargs: object) -> set[int]:
        return {installation_id}

    monkeypatch.setattr(usage_metrics, "_allowed_installation_ids", _fake_allowed_installation_ids)
    async def _fake_provider_metric_config(
        _installation_id: int, _provider: str
    ) -> tuple[bool, list[str], list[str]]:
        return True, ["user_id", "email"], ["provider", "model", "stage"]

    monkeypatch.setattr(usage_metrics, "_provider_metric_config", _fake_provider_metric_config)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            ReviewModelAudit(
                review_id=review_id,
                installation_id=installation_id,
                run_id="run-1",
                stage="primary_review",
                provider="openai",
                model="gpt-5.5",
                input_tokens=120,
                output_tokens=30,
                total_tokens=150,
                metadata_json={"user_id": "123", "repo": "acme/repo", "email": "x@example.com"},
                created_at=now,
            )
        )
        await session.commit()

    response = await client.get(
        f"/api/v1/usage/metrics?installation_id={installation_id}&provider=openai&group_by=model&include_metadata=true",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["group_by"] == "model"
    assert payload["metrics"][0]["dimension"] == "gpt-5.5"
    assert payload["metadata_sample"]["user_id"] == "[REDACTED]"
    assert payload["metadata_sample"]["email"] == "[REDACTED]"


@pytest.mark.anyio
async def test_usage_scorecard_reports_disagreement_and_rates(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id, repo_full_name="acme/repo")
    async def _fake_allowed_installation_ids(*_args: object, **_kwargs: object) -> set[int]:
        return {installation_id}

    monkeypatch.setattr(usage_metrics, "_allowed_installation_ids", _fake_allowed_installation_ids)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            ReviewModelAudit(
                review_id=review_id,
                installation_id=installation_id,
                run_id="run-2",
                stage="fast_path",
                provider="openai",
                model="gpt-5.5",
                decision="skip_review",
                input_tokens=5,
                output_tokens=5,
                total_tokens=10,
                metadata_json={},
            )
        )
        session.add(
            ReviewModelAudit(
                review_id=review_id,
                installation_id=installation_id,
                run_id="run-2",
                stage="challenger",
                provider="openai",
                model="gpt-5.5",
                conflict_score=40,
                input_tokens=5,
                output_tokens=5,
                total_tokens=10,
                metadata_json={},
            )
        )
        await session.commit()

    async def _fake_summary(
        *, installation_id: int | None = None, repo_full_name: str | None = None
    ) -> dict[str, object]:
        assert installation_id is not None
        return {"global_metrics": {"dismiss_rate": 0.1, "ignore_rate": 0.05, "useful_rate": 0.8}}

    monkeypatch.setattr(usage_metrics, "summarize_finding_outcomes", _fake_summary)

    response = await client.get(
        f"/api/v1/usage/scorecard?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_fast_path_calls"] >= 1
    assert payload["disagreement_rate"] > 0
    assert payload["dismiss_rate"] == pytest.approx(0.1)


@pytest.mark.anyio
async def test_usage_metrics_returns_403_when_provider_disabled(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def _fake_allowed_installation_ids(*_args: object, **_kwargs: object) -> set[int]:
        return {installation_id}

    async def _fake_provider_metric_config(
        _installation_id: int, _provider: str
    ) -> tuple[bool, list[str], list[str]]:
        return False, ["user_id"], ["provider"]

    monkeypatch.setattr(usage_metrics, "_allowed_installation_ids", _fake_allowed_installation_ids)
    monkeypatch.setattr(usage_metrics, "_provider_metric_config", _fake_provider_metric_config)

    response = await client.get(
        f"/api/v1/usage/metrics?installation_id={installation_id}&provider=openai&group_by=provider",
        headers=_auth_headers(),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_usage_metrics_returns_400_when_dimension_not_allowed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def _fake_allowed_installation_ids(*_args: object, **_kwargs: object) -> set[int]:
        return {installation_id}

    async def _fake_provider_metric_config(
        _installation_id: int, _provider: str
    ) -> tuple[bool, list[str], list[str]]:
        return True, ["user_id"], ["provider"]

    monkeypatch.setattr(usage_metrics, "_allowed_installation_ids", _fake_allowed_installation_ids)
    monkeypatch.setattr(usage_metrics, "_provider_metric_config", _fake_provider_metric_config)

    response = await client.get(
        f"/api/v1/usage/metrics?installation_id={installation_id}&provider=openai&group_by=stage",
        headers=_auth_headers(),
    )
    assert response.status_code == 400
