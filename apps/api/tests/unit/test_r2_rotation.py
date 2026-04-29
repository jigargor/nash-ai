from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.storage import r2_rotation


def test_parse_r2_credentials_rotated_at_none() -> None:
    assert r2_rotation.parse_r2_credentials_rotated_at(None) is None
    assert r2_rotation.parse_r2_credentials_rotated_at("") is None
    assert r2_rotation.parse_r2_credentials_rotated_at("   ") is None


def test_parse_r2_credentials_rotated_at_date_assumes_utc() -> None:
    parsed = r2_rotation.parse_r2_credentials_rotated_at("2026-04-29")
    assert parsed == datetime(2026, 4, 29, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_r2_credentials_rotated_at_z_suffix() -> None:
    parsed = r2_rotation.parse_r2_credentials_rotated_at("2026-04-29T12:00:00Z")
    assert parsed == datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_r2_credentials_rotated_at_invalid() -> None:
    with pytest.raises(ValueError, match="R2_CREDENTIALS_ROTATED_AT"):
        r2_rotation.parse_r2_credentials_rotated_at("not-a-date")


def test_r2_access_key_max_age_days_effective() -> None:
    prod = Settings.model_construct(
        environment="production", r2_access_key_max_age_days_production=30
    )
    assert r2_rotation.r2_access_key_max_age_days_effective(prod) == 30
    dev = Settings.model_construct(
        environment="development", r2_access_key_max_age_days_development=90
    )
    assert r2_rotation.r2_access_key_max_age_days_effective(dev) == 90


def test_assert_r2_skips_when_r2_not_configured() -> None:
    s = Settings.model_construct(
        r2_endpoint_url=None,
        r2_bucket=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_credentials_rotated_at=None,
    )
    r2_rotation.assert_r2_credentials_within_rotation_policy(s)


def test_assert_r2_requires_rotated_at_when_configured() -> None:
    s = Settings.model_construct(
        r2_endpoint_url="https://x.r2.cloudflarestorage.com",
        r2_bucket="b",
        r2_access_key_id="k",
        r2_secret_access_key="s",
        r2_credentials_rotated_at=None,
        environment="production",
        r2_access_key_max_age_days_production=30,
        r2_access_key_max_age_days_development=90,
    )
    with pytest.raises(RuntimeError, match="R2_CREDENTIALS_ROTATED_AT"):
        r2_rotation.assert_r2_credentials_within_rotation_policy(s)


def test_assert_r2_fails_when_credentials_too_old() -> None:
    old = datetime.now(timezone.utc) - timedelta(days=100)
    s = Settings.model_construct(
        r2_endpoint_url="https://x.r2.cloudflarestorage.com",
        r2_bucket="b",
        r2_access_key_id="k",
        r2_secret_access_key="s",
        r2_credentials_rotated_at=old,
        environment="production",
        r2_access_key_max_age_days_production=30,
        r2_access_key_max_age_days_development=90,
    )
    with pytest.raises(RuntimeError, match="exceed the configured rotation policy"):
        r2_rotation.assert_r2_credentials_within_rotation_policy(s)


def test_assert_r2_ok_when_within_window() -> None:
    recent = datetime.now(timezone.utc) - timedelta(days=5)
    s = Settings.model_construct(
        r2_endpoint_url="https://x.r2.cloudflarestorage.com",
        r2_bucket="b",
        r2_access_key_id="k",
        r2_secret_access_key="s",
        r2_credentials_rotated_at=recent,
        environment="production",
        r2_access_key_max_age_days_production=30,
        r2_access_key_max_age_days_development=90,
    )
    r2_rotation.assert_r2_credentials_within_rotation_policy(s)


def test_assert_r2_max_age_zero_disables_enforcement() -> None:
    old = datetime.now(timezone.utc) - timedelta(days=5000)
    s = Settings.model_construct(
        r2_endpoint_url="https://x.r2.cloudflarestorage.com",
        r2_bucket="b",
        r2_access_key_id="k",
        r2_secret_access_key="s",
        r2_credentials_rotated_at=old,
        environment="production",
        r2_access_key_max_age_days_production=0,
        r2_access_key_max_age_days_development=90,
    )
    r2_rotation.assert_r2_credentials_within_rotation_policy(s)
