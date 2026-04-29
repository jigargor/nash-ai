from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from app.api.auth import get_current_dashboard_user
from app.config import settings


def _encode_dashboard_token(sub: object) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "login": "tester",
        "iss": settings.dashboard_user_jwt_issuer,
        "aud": settings.dashboard_user_jwt_audience,
        "exp": now + timedelta(minutes=10),
    }
    return str(
        jwt.encode(
            payload,
            settings.dashboard_user_jwt_secret,
            algorithm="HS256",
        )
    )


@pytest.fixture(autouse=True)
def _configure_dashboard_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dashboard_user_jwt_secret", "x" * 40)
    monkeypatch.setattr(settings, "dashboard_user_jwt_audience", "dashboard-api")
    monkeypatch.setattr(settings, "dashboard_user_jwt_issuer", "nash-web-dashboard")


def test_get_current_dashboard_user_rejects_non_string_sub() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_dashboard_user(_encode_dashboard_token(123))  # type: ignore[arg-type]
    assert exc_info.value.status_code == 401


def test_get_current_dashboard_user_rejects_non_integer_string_sub() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_dashboard_user(_encode_dashboard_token("abc"))
    assert exc_info.value.status_code == 401


def test_get_current_dashboard_user_rejects_non_positive_sub() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_dashboard_user(_encode_dashboard_token("0"))
    assert exc_info.value.status_code == 401


def test_get_current_dashboard_user_accepts_positive_subject() -> None:
    user = get_current_dashboard_user(_encode_dashboard_token("42"))
    assert user.github_id == 42
    assert user.login == "tester"
