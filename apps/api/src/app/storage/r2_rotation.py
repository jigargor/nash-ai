"""R2 (S3-compatible) access-key rotation policy.

When snapshot archive is enabled, we require ``R2_CREDENTIALS_ROTATED_AT`` and
enforce a maximum credential age so deploys fail loudly instead of silently
losing archive/restore after Cloudflare key expiry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


def parse_r2_credentials_rotated_at(value: object) -> datetime | None:
    """Parse ``R2_CREDENTIALS_ROTATED_AT`` from env (ISO date or datetime, UTC)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "R2_CREDENTIALS_ROTATED_AT must be ISO-8601 (e.g. 2026-04-29 or 2026-04-29T12:00:00Z)"
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def r2_access_key_max_age_days_effective(settings: Settings) -> int:
    if settings.environment.lower() == "production":
        return settings.r2_access_key_max_age_days_production
    return settings.r2_access_key_max_age_days_development


def assert_r2_credentials_within_rotation_policy(settings: Settings) -> None:
    """Raise ``RuntimeError`` if R2 is configured but rotation metadata or age is invalid."""
    if not settings.has_r2_snapshot_archive_configured():
        return

    max_days = r2_access_key_max_age_days_effective(settings)
    if max_days <= 0:
        logger.warning(
            "R2 snapshot archive is configured but R2 access-key max age is disabled "
            "(r2_access_key_max_age_days_* <= 0 for this environment)."
        )
        return

    rotated_at = settings.r2_credentials_rotated_at
    if rotated_at is None:
        raise RuntimeError(
            "R2 snapshot archive is enabled but R2_CREDENTIALS_ROTATED_AT is not set. "
            "Set it to the UTC date you last rotated R2_ACCESS_KEY_ID / "
            "R2_SECRET_ACCESS_KEY in Cloudflare (ISO date, e.g. 2026-04-29)."
        )

    deadline = rotated_at + timedelta(days=max_days)
    now = datetime.now(timezone.utc)
    if now > deadline:
        raise RuntimeError(
            "R2 API credentials exceed the configured max age: "
            f"rotated_at={rotated_at.date().isoformat()}, max_age_days={max_days}, "
            f"environment={settings.environment!r}. Rotate keys in Cloudflare, update "
            "Railway (API + worker) R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY, then set "
            "R2_CREDENTIALS_ROTATED_AT to today's date (UTC)."
        )  # nosec B608 — RuntimeError message text, not SQL execution

    logger.info(
        "R2 credential rotation policy OK (rotated_at=%s, max_age_days=%s, environment=%s).",
        rotated_at.date().isoformat(),
        max_days,
        settings.environment,
    )
