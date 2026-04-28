from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.config import settings
from app.db.models import ApiUsageEvent, InstallationUser, Review, User
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
        cap = int(settings.daily_token_budget_per_installation)
        daily_used = int(daily_tokens or 0)
        weekly_used = int(weekly_tokens or 0)
        cap_ratio = daily_used / cap if cap > 0 else 0.0
        cap_state = "safe"
        if cap_ratio >= 1:
            cap_state = "capped"
        elif cap_ratio >= 0.8:
            cap_state = "near-cap"

        return {
            "installation_id": installation_id,
            "service_breakdown": service_breakdown,
            "daily_requests": daily,
            "weekly_requests": weekly,
            "token_usage": {"daily": daily_used, "weekly": weekly_used},
            "session_cap": {
                "daily_token_budget": cap,
                "daily_used": daily_used,
                "remaining": max(cap - daily_used, 0),
                "state": cap_state,
            },
        }

