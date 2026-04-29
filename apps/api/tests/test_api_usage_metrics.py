from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.api import usage_metrics
from app.config import settings
from app.db.models import ProviderMetricConfig, ReviewModelAudit
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
    assert float(payload["estimated_provider_cost_usd"]) > 0.0
    assert float(payload["estimated_primary_model_cost_usd"]) >= 0.0
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


@pytest.mark.anyio
async def test_usage_metrics_returns_404_when_installation_not_allowed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def _fake_allowed_installation_ids(*_args: object, **_kwargs: object) -> set[int]:
        return set()

    monkeypatch.setattr(usage_metrics, "_allowed_installation_ids", _fake_allowed_installation_ids)

    response = await client.get(
        f"/api/v1/usage/metrics?installation_id={installation_id}&provider=openai&group_by=provider",
        headers=_auth_headers(),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_usage_scorecard_handles_zero_fast_path_rows(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def _fake_allowed_installation_ids(*_args: object, **_kwargs: object) -> set[int]:
        return {installation_id}

    async def _fake_summary(
        *, installation_id: int | None = None, repo_full_name: str | None = None
    ) -> dict[str, object]:
        assert installation_id is not None
        return {"global_metrics": {}}

    monkeypatch.setattr(usage_metrics, "_allowed_installation_ids", _fake_allowed_installation_ids)
    monkeypatch.setattr(usage_metrics, "summarize_finding_outcomes", _fake_summary)

    response = await client.get(
        f"/api/v1/usage/scorecard?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_fast_path_calls"] == 0
    assert payload["fast_path_accept_rate"] == 0.0


@pytest.mark.anyio
async def test_usage_scorecard_returns_404_when_installation_not_allowed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def _fake_allowed_installation_ids(*_args: object, **_kwargs: object) -> set[int]:
        return set()

    monkeypatch.setattr(usage_metrics, "_allowed_installation_ids", _fake_allowed_installation_ids)

    response = await client.get(
        f"/api/v1/usage/scorecard?installation_id={installation_id}",
        headers=_auth_headers(),
    )
    assert response.status_code == 404


def test_redact_metadata_scrubs_user_like_keys() -> None:
    payload = {
        "user_id": "123",
        "actor_name": "alice",
        "email": "a@example.com",
        "model": "gpt-5.5",
    }
    redacted = usage_metrics._redact_metadata(payload, ["user_id", "email"])
    assert redacted["user_id"] == "[REDACTED]"
    assert redacted["email"] == "[REDACTED]"
    assert redacted["actor_name"] == "[REDACTED]"
    assert redacted["model"] == "gpt-5.5"


def test_verify_api_access_rejects_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "secret")
    with pytest.raises(usage_metrics.HTTPException) as exc_info:
        usage_metrics._verify_api_access("wrong")
    assert exc_info.value.status_code == 401


def test_verify_api_access_returns_503_in_production_without_server_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "api_access_key", None)
    with pytest.raises(usage_metrics.HTTPException) as exc_info:
        usage_metrics._verify_api_access("any-header")
    assert exc_info.value.status_code == 503


def test_estimate_provider_audit_cost_skips_unknown_catalog_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        usage_metrics,
        "load_baseline_catalog",
        lambda: SimpleNamespace(find_model=lambda _provider, _model: None),
    )
    total = usage_metrics._estimate_provider_audit_cost_usd(
        "anthropic",
        [("unlikely-model-placeholder-zzz", 1_000_000, 1_000_000)],
    )
    assert total == Decimal("0")


@pytest.mark.anyio
async def test_provider_metric_config_empty_arrays_use_defaults_from_db_row(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)

    async def fake_allowed_installation_ids(
        *_args: object, **_kwargs: object
    ) -> set[int]:
        return {installation_id}

    monkeypatch.setattr(usage_metrics, "_allowed_installation_ids", fake_allowed_installation_ids)
    isolated_provider = f"zzz_metrics_{uuid4().hex}"

    async with AsyncSessionLocal() as session:
        session.add(
            ProviderMetricConfig(
                provider=isolated_provider,
                enabled=True,
                redact_user_fields=[],
                allowed_dimensions=[],
            )
        )
        await session.commit()

    response = await client.get(
        f"/api/v1/usage/metrics"
        f"?installation_id={installation_id}&provider={isolated_provider}&group_by=model",
        headers=_auth_headers(),
    )
    assert response.status_code == 200
