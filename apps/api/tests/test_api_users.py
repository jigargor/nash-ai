"""Tests for the /api/v1/users endpoints (users.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api import users as users_module
from app.api.auth import CurrentDashboardUser
from app.config import settings
from app.crypto import decrypt_secret
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
async def test_verify_api_access_rejects_missing_key_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "required-key")
    with pytest.raises(HTTPException) as exc_info:
        users_module._verify_api_access(None)
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_verify_api_access_accepts_matching_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "required-key")
    users_module._verify_api_access("required-key")


@pytest.mark.anyio
async def test_resolve_user_not_found_raises_404() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await users_module._resolve_user(987654321)
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_resolve_user_deleted_raises_404() -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id, login="deleted-user")
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.github_id == github_id))
        ).scalar_one()
        user.deleted_at = datetime.now(timezone.utc)
        await session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await users_module._resolve_user(github_id)
    assert exc_info.value.status_code == 404


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeHttpxClient:
    def __init__(self, response_status: int | None = None, raise_exc: Exception | None = None):
        self._response_status = response_status
        self._raise_exc = raise_exc

    async def __aenter__(self) -> "_FakeHttpxClient":
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        return None

    async def get(self, *_args: object, **_kwargs: object) -> _FakeResponse:
        if self._raise_exc is not None:
            raise self._raise_exc
        return _FakeResponse(self._response_status or 200)


@pytest.mark.anyio
async def test_validate_api_key_anthropic_401_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users_module.httpx, "AsyncClient", lambda: _FakeHttpxClient(401))
    with pytest.raises(HTTPException) as exc_info:
        await users_module._validate_api_key("anthropic", "bad-key")
    assert exc_info.value.status_code == 422


@pytest.mark.anyio
async def test_validate_api_key_openai_401_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users_module.httpx, "AsyncClient", lambda: _FakeHttpxClient(401))
    with pytest.raises(HTTPException) as exc_info:
        await users_module._validate_api_key("openai", "bad-key")
    assert exc_info.value.status_code == 422


@pytest.mark.anyio
async def test_validate_api_key_timeout_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        users_module.httpx,
        "AsyncClient",
        lambda: _FakeHttpxClient(raise_exc=TimeoutError()),
    )
    with pytest.raises(HTTPException) as exc_info:
        await users_module._validate_api_key("gemini", "slow-key")
    assert exc_info.value.status_code == 422


@pytest.mark.anyio
async def test_validate_api_key_network_failure_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        users_module.httpx,
        "AsyncClient",
        lambda: _FakeHttpxClient(raise_exc=RuntimeError("boom")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await users_module._validate_api_key("openai", "bad-key")
    assert exc_info.value.status_code == 422


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
async def test_users_routes_expired_token_returns_401(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    expired_token = _dashboard_token(github_id, expires_in_seconds=-60)
    response = await client.get(
        "/api/v1/users/me/keys",
        headers={**_auth_headers(), "X-Dashboard-User-Token": expired_token},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_users_routes_forged_signature_returns_401(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    forged_token = _dashboard_token(github_id, secret="forged-secret-that-should-not-verify")
    response = await client.get(
        "/api/v1/users/me/keys",
        headers={**_auth_headers(), "X-Dashboard-User-Token": forged_token},
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
    assert response.json()["requires_terms_acceptance"] is True


@pytest.mark.anyio
async def test_upsert_current_user_terms_flag_false_when_already_accepted(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_id = _rand_github_id()
    monkeypatch.setattr(settings, "terms_version", "v1")
    user_id = await _seed_user(github_id, login="tos-user")
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        user.accepted_terms_version = "v1"
        user.accepted_terms_at = datetime.now(timezone.utc)
        await session.commit()

    response = await client.post(
        "/api/v1/users/me",
        json={"login": "tos-user"},
        headers=_auth_headers_for_user(github_id, login="tos-user"),
    )
    assert response.status_code == 200
    assert response.json()["requires_terms_acceptance"] is False


@pytest.mark.anyio
async def test_terms_status_and_acceptance_round_trip(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_id = _rand_github_id()
    monkeypatch.setattr(settings, "terms_version", "v2026-04")
    await _seed_user(github_id, login="terms-status-user")

    status_before = await client.get(
        "/api/v1/users/me/terms-status",
        headers=_auth_headers_for_user(github_id, login="terms-status-user"),
    )
    assert status_before.status_code == 200
    assert status_before.json()["requires_terms_acceptance"] is True

    accept_response = await client.post(
        "/api/v1/users/me/terms-acceptance",
        headers=_auth_headers_for_user(github_id, login="terms-status-user"),
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["requires_terms_acceptance"] is False
    assert accept_response.json()["accepted_terms_version"] == "v2026-04"

    status_after = await client.get(
        "/api/v1/users/me/terms-status",
        headers=_auth_headers_for_user(github_id, login="terms-status-user"),
    )
    assert status_after.status_code == 200
    assert status_after.json()["requires_terms_acceptance"] is False


@pytest.mark.anyio
async def test_upsert_current_user_encrypts_oauth_token(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    oauth_token = "gho_test_oauth_token_value_abcdefghijklmnopqrstuvwxyz"

    response = await client.post(
        "/api/v1/users/me",
        json={"login": "token-owner", "oauth_token": oauth_token},
        headers=_auth_headers_for_user(github_id, login="token-owner"),
    )
    assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        stored_user = (
            await session.execute(select(User).where(User.github_id == github_id))
        ).scalar_one_or_none()
        assert stored_user is not None
        assert stored_user.token_enc is not None
        assert decrypt_secret(stored_user.token_enc) == oauth_token


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
async def test_sync_user_installations_missing_user_returns_404(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    response = await client.post(
        "/api/v1/users/me/installations-sync",
        json={"installations": []},
        headers=_auth_headers_for_user(github_id, login="missing-user"),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_sync_user_installations_removes_stale_memberships(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    user_id = await _seed_user(github_id, login="sync-prune-user")
    old_installation_id = int(str(uuid4().int)[:9])
    new_installation_id = int(str(uuid4().int)[9:18])

    async with AsyncSessionLocal() as session:
        session.add(Installation(installation_id=old_installation_id, account_login="acme-old", account_type="Org"))
        session.add(InstallationUser(installation_id=old_installation_id, user_id=user_id, role="member"))
        await session.commit()

    response = await client.post(
        "/api/v1/users/me/installations-sync",
        json={
            "installations": [
                {
                    "installation_id": new_installation_id,
                    "account_login": "acme-new",
                    "account_type": "Organization",
                }
            ]
        },
        headers=_auth_headers_for_user(github_id, login="sync-prune-user"),
    )
    assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(InstallationUser).where(InstallationUser.user_id == user_id))
        ).scalars().all()
        installation_ids = {int(row.installation_id) for row in rows}
        assert old_installation_id not in installation_ids
        assert new_installation_id in installation_ids


@pytest.mark.anyio
async def test_sync_installations_direct_covers_existing_installation_update() -> None:
    github_id = _rand_github_id()
    user_id = await _seed_user(github_id, login="direct-sync")
    installation_id = int(str(uuid4().int)[:9])
    async with AsyncSessionLocal() as session:
        session.add(
            Installation(
                installation_id=installation_id,
                account_login="acme-old-login",
                account_type="User",
            )
        )
        session.add(InstallationUser(installation_id=installation_id, user_id=user_id, role="member"))
        await session.commit()

    result = await users_module.sync_current_user_installations(
        users_module.SyncInstallationsRequest(
            installations=[
                users_module.InstallationSyncItem(
                    installation_id=installation_id,
                    account_login="acme-new-login",
                    account_type="Organization",
                )
            ]
        ),
        CurrentDashboardUser(github_id=github_id, login="direct-sync"),
    )
    assert result["linked_installations"] == 1

    async with AsyncSessionLocal() as session:
        installation = (
            await session.execute(
                select(Installation).where(Installation.installation_id == installation_id)
            )
        ).scalar_one()
        assert installation.account_login == "acme-new-login"
        assert installation.account_type == "Organization"


@pytest.mark.anyio
async def test_sync_installations_direct_ignores_invalid_entries() -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id, login="direct-sync-invalid")
    result = await users_module.sync_current_user_installations(
        users_module.SyncInstallationsRequest(
            installations=[
                users_module.InstallationSyncItem(
                    installation_id=-1,
                    account_login="invalid",
                    account_type="Organization",
                ),
                users_module.InstallationSyncItem(
                    installation_id=0,
                    account_login="",
                    account_type="Organization",
                ),
            ]
        ),
        CurrentDashboardUser(github_id=github_id, login="direct-sync-invalid"),
    )
    assert result["linked_installations"] == 0


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
async def test_list_user_keys_missing_user_returns_empty_list(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    response = await client.get("/api/v1/users/me/keys", headers=_auth_headers_for_user(github_id))
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 3
    assert all(item["has_key"] is False for item in items)


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
async def test_upsert_user_key_unsupported_provider_returns_400(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id)
    response = await client.put(
        "/api/v1/users/me/keys/notreal?validate=false",
        json={"api_key": "sk-test-key-long-enough-here"},
        headers=_auth_headers_for_user(github_id),
    )
    assert response.status_code == 400


@pytest.mark.anyio
async def test_upsert_user_key_direct_create_then_update() -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id, login="direct-key-user")

    created = await users_module.upsert_user_key(
        "openai",
        users_module.UpsertKeyRequest(api_key="sk-direct-create-key-long-enough-123"),
        CurrentDashboardUser(github_id=github_id, login="direct-key-user"),
        validate=False,
    )
    assert "created" in created["detail"]

    updated = await users_module.upsert_user_key(
        "openai",
        users_module.UpsertKeyRequest(api_key="sk-direct-update-key-long-enough-456"),
        CurrentDashboardUser(github_id=github_id, login="direct-key-user"),
        validate=False,
    )
    assert "updated" in updated["detail"]


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
async def test_delete_user_key_not_found_returns_404(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id)
    response = await client.delete(
        "/api/v1/users/me/keys/openai",
        headers=_auth_headers_for_user(github_id),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_delete_user_key_direct_unsupported_provider_400() -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id, login="unsupported-delete-user")
    with pytest.raises(HTTPException) as exc_info:
        await users_module.delete_user_key(
            "notreal",
            CurrentDashboardUser(github_id=github_id, login="unsupported-delete-user"),
        )
    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_delete_user_key_direct_missing_user_404() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await users_module.delete_user_key(
            "openai",
            CurrentDashboardUser(github_id=_rand_github_id(), login="missing-user"),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_delete_user_key_direct_happy_path() -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id, login="delete-key-user")
    await users_module.upsert_user_key(
        "anthropic",
        users_module.UpsertKeyRequest(api_key="sk-delete-key-long-enough-123456"),
        CurrentDashboardUser(github_id=github_id, login="delete-key-user"),
        validate=False,
    )
    result = await users_module.delete_user_key(
        "anthropic",
        CurrentDashboardUser(github_id=github_id, login="delete-key-user"),
    )
    assert "deleted" in result["detail"]


@pytest.mark.anyio
async def test_delete_current_user_soft_deletes(client: httpx.AsyncClient) -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id)

    response = await client.delete("/api/v1/users/me", headers=_auth_headers_for_user(github_id))
    assert response.status_code == 200

    response_again = await client.delete("/api/v1/users/me", headers=_auth_headers_for_user(github_id))
    assert response_again.status_code == 404


@pytest.mark.anyio
async def test_delete_current_user_direct_missing_404() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await users_module.delete_current_user(
            CurrentDashboardUser(github_id=_rand_github_id(), login="missing-delete-user")
        )
    assert exc_info.value.status_code == 404


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


@pytest.mark.anyio
async def test_upsert_key_rejects_short_api_key_before_storage(
    client: httpx.AsyncClient,
) -> None:
    github_id = _rand_github_id()
    await _seed_user(github_id)
    response = await client.put(
        "/api/v1/users/me/keys/openai?validate=false",
        json={"api_key": "short"},
        headers=_auth_headers_for_user(github_id),
    )
    assert response.status_code == 422
