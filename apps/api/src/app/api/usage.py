from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.config import settings
from app.db.models import (
    ApiUsageEvent,
    InstallationUser,
    Review,
    ReviewModelAudit,
    User,
    UserProviderKey,
)
from app.db.session import AsyncSessionLocal, set_installation_context


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(  # pragma: no cover
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key auth is not configured"
        )
    if not settings.api_access_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key"
        )


router = APIRouter(
    prefix="/api/v1/usage",
    dependencies=[Depends(_verify_api_access), Depends(get_current_dashboard_user)],
)


async def _allowed_installation_ids(current_user: CurrentDashboardUser) -> set[int]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(InstallationUser.installation_id)
                .join(User, User.id == InstallationUser.user_id)
                .where(User.github_id == current_user.github_id)
                .where(User.deleted_at.is_(None))
            )
        ).scalars()
        return {int(installation_id) for installation_id in rows}


def _require_installation_access(allowed_installation_ids: set[int], installation_id: int) -> None:
    if installation_id not in allowed_installation_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found")


@router.get("/summary")
async def get_usage_summary(
    installation_id: int = Query(..., ge=1),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, installation_id)
    now = datetime.now(timezone.utc)
    day_start = now - timedelta(days=1)
    week_start = now - timedelta(days=7)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)

        service_rows = await session.execute(
            select(ApiUsageEvent.service, func.count(ApiUsageEvent.id))
            .where(ApiUsageEvent.installation_id == installation_id)
            .where(ApiUsageEvent.occurred_at >= week_start)
            .group_by(ApiUsageEvent.service)
            .order_by(func.count(ApiUsageEvent.id).desc())
        )
        service_breakdown = [
            {"service": str(service), "requests": int(total)}
            for service, total in service_rows.all()
        ]

        daily_rows = await session.execute(
            select(
                func.date_trunc("day", ApiUsageEvent.occurred_at).label("bucket"),
                func.count(ApiUsageEvent.id),
            )
            .where(ApiUsageEvent.installation_id == installation_id)
            .where(ApiUsageEvent.occurred_at >= week_start)
            .group_by("bucket")
            .order_by("bucket")
        )
        daily = [
            {"bucket": bucket.isoformat() if bucket is not None else "", "requests": int(total)}
            for bucket, total in daily_rows.all()
        ]

        weekly_rows = await session.execute(
            select(
                func.date_trunc("week", ApiUsageEvent.occurred_at).label("bucket"),
                func.count(ApiUsageEvent.id),
            )
            .where(ApiUsageEvent.installation_id == installation_id)
            .where(ApiUsageEvent.occurred_at >= now - timedelta(days=30))
            .group_by("bucket")
            .order_by("bucket")
        )
        weekly = [
            {"bucket": bucket.isoformat() if bucket is not None else "", "requests": int(total)}
            for bucket, total in weekly_rows.all()
        ]

        daily_tokens = await session.scalar(
            select(func.coalesce(func.sum(Review.tokens_used), 0))
            .where(Review.installation_id == installation_id)
            .where(Review.created_at >= day_start)
        )
        weekly_tokens = await session.scalar(
            select(func.coalesce(func.sum(Review.tokens_used), 0))
            .where(Review.installation_id == installation_id)
            .where(Review.created_at >= week_start)
        )
        provider_daily_rows = await session.execute(
            select(
                func.coalesce(ReviewModelAudit.provider, "unknown").label("provider"),
                func.coalesce(func.sum(ReviewModelAudit.total_tokens), 0).label("tokens"),
            )
            .where(ReviewModelAudit.installation_id == installation_id)
            .where(ReviewModelAudit.created_at >= day_start)
            .group_by("provider")
            .order_by("provider")
        )
        provider_weekly_rows = await session.execute(
            select(
                func.coalesce(ReviewModelAudit.provider, "unknown").label("provider"),
                func.coalesce(func.sum(ReviewModelAudit.total_tokens), 0).label("tokens"),
            )
            .where(ReviewModelAudit.installation_id == installation_id)
            .where(ReviewModelAudit.created_at >= week_start)
            .group_by("provider")
            .order_by("provider")
        )
        cap = int(settings.daily_token_budget_per_installation)
        daily_used = int(daily_tokens or 0)
        weekly_used = int(weekly_tokens or 0)
        cap_ratio = daily_used / cap if cap > 0 else 0.0
        cap_state = "safe"
        if cap_ratio >= 1:
            cap_state = "capped"
        elif cap_ratio >= 0.8:
            cap_state = "near-cap"

        daily_cost_total = await session.scalar(
            select(func.coalesce(func.sum(Review.cost_usd), 0))
            .where(Review.installation_id == installation_id)
            .where(Review.created_at >= day_start)
        )
        weekly_cost_total = await session.scalar(
            select(func.coalesce(func.sum(Review.cost_usd), 0))
            .where(Review.installation_id == installation_id)
            .where(Review.created_at >= week_start)
        )

        daily_cost_per_token = (
            float(daily_cost_total or 0) / daily_used if daily_used > 0 else 0.0
        )
        weekly_cost_per_token = (
            float(weekly_cost_total or 0) / weekly_used if weekly_used > 0 else 0.0
        )

        provider_daily: dict[str, dict[str, object]] = {}
        for provider, tokens in provider_daily_rows.all():
            provider_name = str(provider)
            daily_provider_tokens = int(tokens or 0)
            provider_daily[str(provider)] = {
                "provider": provider_name,
                "daily_tokens": daily_provider_tokens,
                "daily_cost_usd": str(daily_provider_tokens * daily_cost_per_token),
                "weekly_tokens": 0,
                "weekly_cost_usd": "0",
                "effective_cap_tokens": cap,
            }
        for provider, tokens in provider_weekly_rows.all():
            key = str(provider)
            weekly_provider_tokens = int(tokens or 0)
            row = provider_daily.setdefault(
                key,
                {
                    "provider": key,
                    "daily_tokens": 0,
                    "daily_cost_usd": "0",
                    "weekly_tokens": 0,
                    "weekly_cost_usd": "0",
                    "effective_cap_tokens": cap,
                },
            )
            row["weekly_tokens"] = weekly_provider_tokens
            row["weekly_cost_usd"] = str(weekly_provider_tokens * weekly_cost_per_token)

        provider_caps = sorted(provider_daily.values(), key=lambda row: str(row["provider"]))

        configured_rows = await session.execute(
            select(UserProviderKey.provider)
            .join(User, User.id == UserProviderKey.user_id)
            .where(User.github_id == current_user.github_id)
            .where(User.deleted_at.is_(None))
            .order_by(UserProviderKey.provider)
        )
        configured_providers = sorted({str(row[0]) for row in configured_rows.all()})

        return {
            "installation_id": installation_id,
            "service_breakdown": service_breakdown,
            "daily_requests": daily,
            "weekly_requests": weekly,
            "token_usage": {"daily": daily_used, "weekly": weekly_used},
            "configured_providers": configured_providers,
            "configured_provider_count": len(configured_providers),
            "api_key_caps": provider_caps,
            "cumulative_caps": {
                "daily_tokens": daily_used,
                "weekly_tokens": weekly_used,
                "daily_token_budget": cap,
                "state": cap_state,
            },
            "session_cap": {
                "daily_token_budget": cap,
                "daily_used": daily_used,
                "remaining": max(cap - daily_used, 0),
                "state": cap_state,
            },
        }

