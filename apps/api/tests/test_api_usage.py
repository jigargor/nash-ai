from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.api import usage as usage_router
from app.config import settings
from app.db.models import ReviewModelAudit
from app.db.session import AsyncSessionLocal, set_installation_context

from conftest import _auth_headers, _insert_installation, _insert_review, _random_installation_id


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
async def client(test_app: FastAPI) -> httpx.AsyncIterator[httpx.AsyncClient]:
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
