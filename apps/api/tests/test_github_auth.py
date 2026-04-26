import asyncio

import pytest

from app.github import auth

def test_create_jwt_uses_expected_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_encode(payload: dict[str, int | str], key: str, algorithm: str) -> str:
        captured["payload"] = payload
        captured["key"] = key
        captured["algorithm"] = algorithm
        return "jwt-token"

    monkeypatch.setattr(auth, "_load_private_key", lambda: "private-key")
    monkeypatch.setattr(auth.settings, "github_app_id", "12345")
    monkeypatch.setattr(auth.time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(auth.jwt, "encode", fake_encode)

    token = auth.create_jwt()

    assert token == "jwt-token"
    assert captured["algorithm"] == "RS256"
    assert captured["key"] == "private-key"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["iss"] == "12345"
    assert payload["iat"] == 1_700_000_000 - 60
    assert payload["exp"] == 1_700_000_000 + 600


def test_get_installation_token_posts_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(auth, "create_jwt", lambda: "jwt-token")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"token": "installation-token"}

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(
            self, url: str, headers: dict[str, str] | None = None, json: dict | None = None, **_: object
        ) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeClient)

    token = asyncio.run(auth.get_installation_token(987))

    assert token == "installation-token"
    assert captured["url"] == "https://api.github.com/app/installations/987/access_tokens"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer jwt-token"
    assert headers["Accept"] == "application/vnd.github+json"
    assert captured["json"] == {}
