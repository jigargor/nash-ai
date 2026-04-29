from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api import models_catalog as models_catalog_module
from app.config import settings

from conftest import _auth_headers, _dashboard_user_token


@pytest.fixture(autouse=True)
def _configure_dashboard_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dashboard_user_jwt_secret", "test-dashboard-user-secret")
    monkeypatch.setattr(settings, "dashboard_user_jwt_audience", "dashboard-api")
    monkeypatch.setattr(settings, "dashboard_user_jwt_issuer", "nash-web-dashboard")


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(models_catalog_module.router)
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.mark.anyio
async def test_models_catalog_returns_baseline_with_hash_and_pricing(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)

    response = await client.get("/api/v1/models/catalog", headers=_auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"]
    assert isinstance(payload["catalog_hash"], str) and len(payload["catalog_hash"]) == 40
    assert "baseline.yaml" in str(payload["sources_note"])
    catalog = payload["catalog"]
    assert isinstance(catalog, dict)
    provider_slugs = {p["provider"] for p in catalog["providers"]}
    assert {"anthropic", "openai", "gemini"}.issubset(provider_slugs)
    assert any(m["provider"] == "anthropic" for m in catalog["models"])


def _dashboard_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    merged: dict[str, str] = {"X-Dashboard-User-Token": _dashboard_user_token()}
    if extra:
        merged.update(extra)
    return merged


@pytest.mark.anyio
async def test_models_catalog_requires_valid_api_key_when_configured(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "catalog-test-api-key")

    missing = await client.get("/api/v1/models/catalog", headers=_dashboard_headers())
    assert missing.status_code == 401

    bad = await client.get(
        "/api/v1/models/catalog",
        headers=_dashboard_headers({"X-Api-Key": "wrong"}),
    )
    assert bad.status_code == 401

    ok = await client.get(
        "/api/v1/models/catalog",
        headers=_dashboard_headers({"X-Api-Key": "catalog-test-api-key"}),
    )
    assert ok.status_code == 200
    assert "catalog_hash" in ok.json()


def test_verify_api_access_allows_when_key_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", None)

    models_catalog_module._verify_api_access(None)


def test_verify_api_access_rejects_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "secret")

    with pytest.raises(HTTPException) as exc_info:
        models_catalog_module._verify_api_access("wrong")

    assert exc_info.value.status_code == 401
