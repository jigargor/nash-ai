from __future__ import annotations

import hmac
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import Select, case, func, select

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.db.models import InstallationUser, ProviderMetricConfig, Review, ReviewModelAudit, User
from app.db.session import AsyncSessionLocal, set_installation_context
from app.llm.catalog.loader import load_baseline_catalog
from app.agent.threshold_tuner import get_cached_judge_gate_window
from app.telemetry.finding_outcomes import summarize_finding_outcomes
from app.config import settings

GroupBy = Literal["provider", "model", "stage"]

DEFAULT_REDACT_FIELDS = ["github_id", "user_id", "user_login", "email", "actor", "author", "username"]
USER_KEY_PATTERN = re.compile(r"(user|login|email|actor|author|github)", re.IGNORECASE)


def _estimate_provider_audit_cost_usd(
    provider: str, model_rollups: list[tuple[str, int, int]]
) -> Decimal:
    catalog = load_baseline_catalog()
    total = Decimal("0")
    for model, input_tokens, output_tokens in model_rollups:
        model_record = catalog.find_model(provider, model)
        if model_record is None:
            continue
        pricing = model_record.pricing
        if pricing.input_per_1m is not None:
            total += (Decimal(max(input_tokens, 0)) / Decimal(1_000_000)) * pricing.input_per_1m
        if pricing.output_per_1m is not None:
            total += (Decimal(max(output_tokens, 0)) / Decimal(1_000_000)) * pricing.output_per_1m
    return total


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(
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


def _redact_metadata(value: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    redacted = dict(value)
    for key in list(redacted.keys()):
        lowered = key.lower()
        if lowered in fields or USER_KEY_PATTERN.search(lowered):
            redacted[key] = "[REDACTED]"
    return redacted


async def _provider_metric_config(
    installation_id: int, provider: str
) -> tuple[bool, list[str], list[str]]:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        row = await session.scalar(
            select(ProviderMetricConfig).where(ProviderMetricConfig.provider == provider)
        )
    if row is None:
        return True, DEFAULT_REDACT_FIELDS, ["provider", "model", "stage"]
    redaction = [str(item).lower() for item in row.redact_user_fields if isinstance(item, str)]
    dimensions = [str(item) for item in row.allowed_dimensions if isinstance(item, str)]
    if not redaction:
        redaction = DEFAULT_REDACT_FIELDS
    if not dimensions:
        dimensions = ["provider", "model", "stage"]
    return bool(row.enabled), redaction, dimensions


@router.get("/metrics")
async def get_provider_usage_metrics(
    installation_id: int = Query(..., ge=1),
    provider: str = Query(..., min_length=1),
    group_by: GroupBy = Query(default="provider"),
    days: int = Query(default=7, ge=1, le=90),
    include_metadata: bool = Query(default=False),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, installation_id)
    enabled, redaction_fields, allowed_dimensions = await _provider_metric_config(
        installation_id, provider
    )
    if not enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Provider metrics disabled")
    if group_by not in allowed_dimensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"group_by '{group_by}' is not enabled for provider config",
        )

    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        dim_col = {
            "provider": ReviewModelAudit.provider,
            "model": ReviewModelAudit.model,
            "stage": ReviewModelAudit.stage,
        }[group_by]
        stmt: Select[Any] = (
            select(
                dim_col.label("dimension"),
                func.count(ReviewModelAudit.id).label("calls"),
                func.coalesce(func.sum(ReviewModelAudit.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(ReviewModelAudit.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(ReviewModelAudit.total_tokens), 0).label("total_tokens"),
            )
            .where(ReviewModelAudit.installation_id == installation_id)
            .where(ReviewModelAudit.provider == provider)
            .where(ReviewModelAudit.created_at >= since)
            .group_by("dimension")
            .order_by("dimension")
        )
        rows = (await session.execute(stmt)).all()

        review_cost = await session.scalar(
            select(func.coalesce(func.sum(Review.cost_usd), 0))
            .where(Review.installation_id == installation_id)
            .where(Review.model_provider == provider)
            .where(Review.created_at >= since)
        )
        audit_rollups = (
            await session.execute(
                select(
                    ReviewModelAudit.model,
                    func.coalesce(func.sum(ReviewModelAudit.input_tokens), 0),
                    func.coalesce(func.sum(ReviewModelAudit.output_tokens), 0),
                )
                .where(ReviewModelAudit.installation_id == installation_id)
                .where(ReviewModelAudit.provider == provider)
                .where(ReviewModelAudit.created_at >= since)
                .group_by(ReviewModelAudit.model)
            )
        ).all()

        metadata_sample: dict[str, Any] | None = None
        if include_metadata:
            sample = await session.scalar(
                select(ReviewModelAudit.metadata_json)
                .where(ReviewModelAudit.installation_id == installation_id)
                .where(ReviewModelAudit.provider == provider)
                .order_by(ReviewModelAudit.created_at.desc())
                .limit(1)
            )
            if isinstance(sample, dict):
                metadata_sample = _redact_metadata(sample, redaction_fields)

    metrics = [
        {
            "dimension": str(row.dimension),
            "calls": int(row.calls or 0),
            "input_tokens": int(row.input_tokens or 0),
            "output_tokens": int(row.output_tokens or 0),
            "total_tokens": int(row.total_tokens or 0),
        }
        for row in rows
    ]
    return {
        "installation_id": installation_id,
        "provider": provider,
        "group_by": group_by,
        "window_days": days,
        "estimated_provider_cost_usd": str(
            _estimate_provider_audit_cost_usd(
                provider,
                [
                    (
                        str(row.model),
                        int(row[1] or 0),
                        int(row[2] or 0),
                    )
                    for row in audit_rollups
                ],
            )
        ),
        "estimated_primary_model_cost_usd": str(review_cost or 0),
        "metrics": metrics,
        "metadata_sample": metadata_sample,
    }


@router.get("/traceability")
async def get_traceability_report(
    installation_id: int = Query(..., ge=1),
    review_id: int | None = Query(default=None, ge=1),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    """Report how well durable audit rows can be traversed back to observer traces."""
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, installation_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        stmt = (
            select(ReviewModelAudit)
            .where(ReviewModelAudit.installation_id == installation_id)
            .where(ReviewModelAudit.created_at >= since)
            .order_by(ReviewModelAudit.created_at.desc())
            .limit(limit)
        )
        if review_id is not None:
            stmt = stmt.where(ReviewModelAudit.review_id == review_id)
        audits = (await session.execute(stmt)).scalars().all()

    stage_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    reviews: dict[int, dict[str, object]] = {}
    linked_rows = 0
    generation_rows = 0
    stage_duration_values: list[int] = []

    for audit in audits:
        metadata = audit.metadata_json if isinstance(audit.metadata_json, dict) else {}
        trace_id = metadata.get("trace_id")
        generation_id = metadata.get("generation_id")
        has_trace = isinstance(trace_id, str) and bool(trace_id.strip())
        has_generation = isinstance(generation_id, str) and bool(generation_id.strip())
        if has_trace:
            linked_rows += 1
        if has_generation:
            generation_rows += 1
        if isinstance(audit.stage_duration_ms, int):
            stage_duration_values.append(audit.stage_duration_ms)

        stage_counts[audit.stage] = stage_counts.get(audit.stage, 0) + 1
        provider_counts[audit.provider] = provider_counts.get(audit.provider, 0) + 1
        model_counts[audit.model] = model_counts.get(audit.model, 0) + 1

        summary = reviews.setdefault(
            int(audit.review_id),
            {
                "review_id": int(audit.review_id),
                "run_ids": set(),
                "stages": set(),
                "providers": set(),
                "models": set(),
                "total_tokens": 0,
                "trace_linked_rows": 0,
                "generation_linked_rows": 0,
            },
        )
        cast_set(summary, "run_ids").add(audit.run_id)
        cast_set(summary, "stages").add(audit.stage)
        cast_set(summary, "providers").add(audit.provider)
        cast_set(summary, "models").add(audit.model)
        summary["total_tokens"] = _int_summary_value(summary, "total_tokens") + int(
            audit.total_tokens or 0
        )
        if has_trace:
            summary["trace_linked_rows"] = _int_summary_value(summary, "trace_linked_rows") + 1
        if has_generation:
            summary["generation_linked_rows"] = (
                _int_summary_value(summary, "generation_linked_rows") + 1
            )

    review_summaries = []
    for summary in reviews.values():
        review_summaries.append(
            {
                "review_id": summary["review_id"],
                "run_ids": sorted(cast_set(summary, "run_ids")),
                "stages": sorted(cast_set(summary, "stages")),
                "providers": sorted(cast_set(summary, "providers")),
                "models": sorted(cast_set(summary, "models")),
                "total_tokens": summary["total_tokens"],
                "trace_linked_rows": summary["trace_linked_rows"],
                "generation_linked_rows": summary["generation_linked_rows"],
            }
        )

    row_count = len(audits)
    return {
        "installation_id": installation_id,
        "review_id": review_id,
        "window_days": days,
        "row_count": row_count,
        "review_count": len(reviews),
        "trace_linked_row_count": linked_rows,
        "trace_link_coverage": linked_rows / row_count if row_count else 0.0,
        "generation_linked_row_count": generation_rows,
        "generation_link_coverage": generation_rows / row_count if row_count else 0.0,
        "stage_counts": dict(sorted(stage_counts.items())),
        "provider_counts": dict(sorted(provider_counts.items())),
        "model_counts": dict(sorted(model_counts.items())),
        "latency": {
            "sample_count": len(stage_duration_values),
            "max_stage_duration_ms": max(stage_duration_values) if stage_duration_values else None,
            "avg_stage_duration_ms": (
                sum(stage_duration_values) / len(stage_duration_values)
                if stage_duration_values
                else None
            ),
        },
        "reviews": review_summaries[:100],
    }


def cast_set(summary: dict[str, object], key: str) -> set[str]:
    value = summary[key]
    return value if isinstance(value, set) else set()


def _int_summary_value(summary: dict[str, object], key: str) -> int:
    value = summary[key]
    return value if isinstance(value, int) else 0


@router.get("/scorecard")
async def get_fast_path_scorecard(
    installation_id: int = Query(..., ge=1),
    repo_full_name: str | None = Query(default=None),
    days: int = Query(default=14, ge=1, le=90),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    allowed_installation_ids = await _allowed_installation_ids(current_user)
    _require_installation_access(allowed_installation_ids, installation_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        fast_stmt = (
            select(
                func.count(ReviewModelAudit.id),
                func.coalesce(
                    func.sum(case((ReviewModelAudit.decision == "skip_review", 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((ReviewModelAudit.decision == "light_review", 1), else_=0)),
                    0,
                ),
            )
            .where(ReviewModelAudit.installation_id == installation_id)
            .where(ReviewModelAudit.stage == "fast_path")
            .where(ReviewModelAudit.created_at >= since)
        )
        total_fast, skipped, light = (await session.execute(fast_stmt)).one()
        disagreement_stmt = (
            select(
                func.count(ReviewModelAudit.id),
                func.coalesce(
                    func.sum(case((ReviewModelAudit.conflict_score > 0, 1), else_=0)), 0
                ),
            )
            .where(ReviewModelAudit.installation_id == installation_id)
            .where(ReviewModelAudit.stage.in_(["challenger", "tie_break", "final_post"]))
            .where(ReviewModelAudit.created_at >= since)
        )
        total_debate, disagreements = (await session.execute(disagreement_stmt)).one()
    outcomes = await summarize_finding_outcomes(
        installation_id=installation_id, repo_full_name=repo_full_name
    )
    metrics_raw = outcomes.get("global_metrics", {})
    metrics = metrics_raw if isinstance(metrics_raw, dict) else {}
    total_fast_int = int(total_fast or 0)
    total_debate_int = int(total_debate or 0)
    disagreement_rate = (
        int(disagreements or 0) / total_debate_int if total_debate_int > 0 else 0.0
    )
    judge_window = await get_cached_judge_gate_window(installation_id)
    judge_metrics_raw = (
        judge_window.get("judge_gate_metrics", {})
        if isinstance(judge_window, dict)
        else {}
    )
    judge_metrics = judge_metrics_raw if isinstance(judge_metrics_raw, dict) else {}
    tuner_action = (
        str(judge_window.get("tuner_action"))
        if isinstance(judge_window, dict) and judge_window.get("tuner_action") is not None
        else None
    )
    lowering_authorized = bool(
        tuner_action == "lower_threshold"
        or (
            isinstance(tuner_action, str)
            and tuner_action.startswith("raise")
            and "hold_judge_gate_" not in tuner_action
        )
        or (
            isinstance(judge_metrics.get("is_available"), bool)
            and isinstance(judge_metrics.get("provider_independent"), bool)
            and bool(judge_metrics.get("is_available"))
            and bool(judge_metrics.get("provider_independent"))
        )
    )
    return {
        "installation_id": installation_id,
        "repo_full_name": repo_full_name,
        "window_days": days,
        "total_fast_path_calls": total_fast_int,
        "fast_path_accept_rate": (
            (int(skipped or 0) + int(light or 0)) / total_fast_int if total_fast_int > 0 else 0.0
        ),
        "disagreement_rate": disagreement_rate,
        "dismiss_rate": float(metrics.get("dismiss_rate", 0.0) or 0.0),
        "ignore_rate": float(metrics.get("ignore_rate", 0.0) or 0.0),
        "useful_rate": float(metrics.get("useful_rate", 0.0) or 0.0),
        "threshold_lowering_authorized": lowering_authorized,
        "judge_gate_window": {
            "is_available": bool(judge_metrics.get("is_available", False)),
            "provider_independent": bool(judge_metrics.get("provider_independent", False)),
            "sample_size": int(judge_metrics.get("sample_size", 0) or 0),
            "false_negative_rate": (
                float(judge_metrics["false_negative_rate"])
                if judge_metrics.get("false_negative_rate") is not None
                else None
            ),
            "false_positive_rate": (
                float(judge_metrics["false_positive_rate"])
                if judge_metrics.get("false_positive_rate") is not None
                else None
            ),
            "inconclusive_rate": (
                float(judge_metrics["inconclusive_rate"])
                if judge_metrics.get("inconclusive_rate") is not None
                else None
            ),
            "reliability_score": (
                float(judge_metrics["reliability_score"])
                if judge_metrics.get("reliability_score") is not None
                else None
            ),
            "tuner_action": tuner_action,
            "recorded_at": (
                str(judge_window.get("recorded_at"))
                if isinstance(judge_window, dict) and judge_window.get("recorded_at") is not None
                else None
            ),
        },
        "goldilocks_target": {"min_disagreement_rate": 0.05, "max_disagreement_rate": 0.15},
    }
