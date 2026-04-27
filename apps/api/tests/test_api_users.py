"""Tests for the /api/v1/users endpoints (users.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api import users as users_module
from app.config import settings
from app.db.models import Installation, InstallationUser, User, UserProviderKey
from app.db.session import AsyncSessionLocal, engine
from conftest import _auth_headers


def _rand_github_id() -> int:
    return int(str(uuid4().int)[:9])


def _dashboard_token(
    github_id: int,
    *,
    login: str = "testuser",
    expires_in_seconds: int = 300,
    audience: str | None = None,
    issuer: str | None = None,
    secret: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(github_id),
        "login": login,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
        "aud": audience or settings.dashboard_user_jwt_audience,
        "iss": issuer or settings.dashboard_user_jwt_issuer,
    }
    return jwt.encode(payload, secret or settings.dashboard_user_jwt_secret or "", algorithm="HS256")


def _auth_headers_for_user(github_id: int, *, login: str = "testuser") -> dict[str, str]:
    return {
        **_auth_headers(),
        "X-Dashboard-User-Token": _dashboard_token(github_id, login=login),
    }


@pytest.fixture(autouse=True)
async def reset_db_pool_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset DB pool and auth settings before each test."""
    await engine.dispose()
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", None)
    monkeypatch.setattr(settings, "dashboard_user_jwt_secret", "test-dashboard-secret-is-at-least-32b")
    monkeypatch.setattr(settings, "dashboard_user_jwt_audience", "dashboard-api")
    monkeypatch.setattr(settings, "dashboard_user_jwt_issuer", "nash-web-dashboard")


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(users_module.router)
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> httpx.AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _seed_user(github_id: int, login: str = "testuser") -> int:
    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(User)
            .values(github_id=github_id, login=login, updated_at=datetime.now(timezone.utc))
            .on_conflict_do_update(
                index_elements=["github_id"],
                set_={"login": login, "updated_at": datetime.now(timezone.utc)},
            )
            .returning(User.id)
        )
        user_id = (await session.execute(stmt)).scalar_one()
        await session.commit()
    return int(user_id)


@pytest.mark.anyio
async def test_users_routes_missing_token_returns_401(client: httpx.AsyncClient) -> None:
    headers = _auth_headers()
    headers.pop("X-Dashboard-User-Token", None)
    response = await client.get("/api/v1/users/me/keys", headers=headers)
    assert response.status_code == 401


@pytest.mark.anyio
async def test_users_routes_invalid_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/users/me/keys",
        headers={**_auth_headers(), "X-Dashboard-User-Token": "not-a-token"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_users_routes_wrong_audience_returns_401(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    token = _dashboard_token(github_id, audience="wrong-audience")
    response = await client.get(
        "/api/v1/users/me/keys",
        headers={**_auth_headers(), "X-Dashboard-User-Token": token},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_upsert_current_user_ignores_spoofed_body_github_id(client: httpx.AsyncClient) -> None:
    token_user_id = _rand_github_id()
    spoofed_body_id = _rand_github_id()
    response = await client.post(
        "/api/v1/users/me",
        json={"github_id": spoofed_body_id, "login": "trusted-login"},
        headers=_auth_headers_for_user(token_user_id, login="trusted-login"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["github_id"] == token_user_id
    assert body["github_id"] != spoofed_body_id


@pytest.mark.anyio
async def test_upsert_current_user_uses_token_login_when_body_omits_login(
    client: httpx.AsyncClient,
) -> None:
    github_id = _rand_github_id()
    response = await client.post(
        "/api/v1/users/me",
        json={},
        headers=_auth_headers_for_user(github_id, login="token-login"),
    )
    assert response.status_code == 200
    assert response.json()["login"] == "token-login"


@pytest.mark.anyio
async def test_sync_user_installations_upserts_membership(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id, login="sync-user")

    response = await client.post(
        "/api/v1/users/me/installations-sync",
        json={
            "installations": [
                {
                    "installation_id": 123456789,
                    "account_login": "acme-org",
                    "account_type": "Organization",
                }
            ]
        },
        headers=_auth_headers_for_user(github_id, login="sync-user"),
    )
    assert response.status_code == 200
    assert response.json()["linked_installations"] == 1

    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.github_id == github_id))
        ).scalar_one()
        installation = (
            await session.execute(
                select(Installation).where(Installation.installation_id == 123456789)
            )
        ).scalar_one_or_none()
        assert installation is not None
        link = (
            await session.execute(
                select(InstallationUser).where(
                    InstallationUser.installation_id == 123456789,
                    InstallationUser.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        assert link is not None


@pytest.mark.anyio
async def test_list_user_keys_ignores_spoofed_header_identity(client: httpx.AsyncClient) -> None:
    token_user_id = _rand_github_id()
    spoofed_header_user_id = _rand_github_id()
    user_id = await _seed_user(token_user_id)

    from app.crypto import encrypt_secret

    async with AsyncSessionLocal() as session:
        session.add(
            UserProviderKey(
                user_id=user_id,
                provider="anthropic",
                key_enc=encrypt_secret("sk-test-key-that-is-at-least-20-chars"),
            )
        )
        await session.commit()

    response = await client.get(
        "/api/v1/users/me/keys",
        headers={
            **_auth_headers_for_user(token_user_id),
            "X-User-Github-Id": str(spoofed_header_user_id),
        },
    )
    assert response.status_code == 200
    result = {item["provider"]: item for item in response.json()}
    assert result["anthropic"]["has_key"] is True


@pytest.mark.anyio
async def test_upsert_user_key_uses_token_subject_not_spoofed_header(
    client: httpx.AsyncClient,
) -> None:
    token_user_id = _rand_github_id()
    other_user_id = _rand_github_id()
    token_db_user_id = await _seed_user(token_user_id, login="token-user")
    other_db_user_id = await _seed_user(other_user_id, login="other-user")

    response = await client.put(
        "/api/v1/users/me/keys/openai?validate=false",
        json={"api_key": "sk-token-user-key-long-enough-here"},
        headers={
            **_auth_headers_for_user(token_user_id),
            "X-User-Github-Id": str(other_user_id),
        },
    )
    assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        token_user_key = (
            await session.execute(
                select(UserProviderKey).where(
                    UserProviderKey.user_id == token_db_user_id,
                    UserProviderKey.provider == "openai",
                )
            )
        ).scalar_one_or_none()
        assert token_user_key is not None
        other_user_key = (
            await session.execute(
                select(UserProviderKey).where(
                    UserProviderKey.user_id == other_db_user_id,
                    UserProviderKey.provider == "openai",
                )
            )
        ).scalar_one_or_none()
        assert other_user_key is None


@pytest.mark.anyio
async def test_upsert_and_delete_user_key_happy_path(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    user_id = await _seed_user(github_id)

    create_response = await client.put(
        "/api/v1/users/me/keys/anthropic?validate=false",
        json={"api_key": "sk-test-key-long-enough-here"},
        headers=_auth_headers_for_user(github_id),
    )
    assert create_response.status_code == 200

    async with AsyncSessionLocal() as session:
        key_row = (
            await session.execute(
                select(UserProviderKey).where(
                    UserProviderKey.user_id == user_id,
                    UserProviderKey.provider == "anthropic",
                )
            )
        ).scalar_one_or_none()
        assert key_row is not None

    delete_response = await client.delete(
        "/api/v1/users/me/keys/anthropic",
        headers=_auth_headers_for_user(github_id),
    )
    assert delete_response.status_code == 200


@pytest.mark.anyio
async def test_delete_current_user_soft_deletes(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id)

    response = await client.delete("/api/v1/users/me", headers=_auth_headers_for_user(github_id))
    assert response.status_code == 200

    response_again = await client.delete("/api/v1/users/me", headers=_auth_headers_for_user(github_id))
    assert response_again.status_code == 404


@pytest.mark.anyio
async def test_dashboard_token_secret_missing_fails_closed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_id = _rand_github_id()
    valid_token = _dashboard_token(github_id)
    monkeypatch.setattr(settings, "dashboard_user_jwt_secret", None)
    response = await client.get(
        "/api/v1/users/me/keys",
        headers={**_auth_headers(), "X-Dashboard-User-Token": valid_token},
    )
    assert response.status_code == 503
