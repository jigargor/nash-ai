import hmac
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select

from app.config import settings
from app.db.models import BenchmarkResult, BenchmarkRun, FindingOutcome, Review
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    # When API_ACCESS_KEY is unset the entire API is open — intended for local dev only.
    # Production deployments must set API_ACCESS_KEY; the check below enforces that.
    # Staging/preview envs should also set API_ACCESS_KEY to prevent data leakage.
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


router = APIRouter(prefix="/api/v1/benchmarks", dependencies=[Depends(_verify_api_access)])


@router.get("/runs")
async def list_benchmark_runs(limit: int = Query(default=20, ge=1, le=200)) -> list[dict[str, Any]]:
    """List recent benchmark runs with summary totals."""
    async with AsyncSessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(BenchmarkRun).order_by(BenchmarkRun.started_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "id": run.id,
            "name": run.name,
            "prompt_version": run.prompt_version,
            "dataset_path": run.dataset_path,
            "triggered_by": run.triggered_by,
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "totals": run.totals_json,
        }
        for run in rows
    ]


@router.get("/runs/{run_id}")
async def get_benchmark_run(run_id: int) -> dict[str, Any]:
    """Full results for a benchmark run including per-case breakdown."""
    async with AsyncSessionLocal() as session:
        run = await session.get(BenchmarkRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Benchmark run not found")
        results = (
            (
                await session.execute(
                    select(BenchmarkResult)
                    .where(BenchmarkResult.run_id == run_id)
                    .order_by(BenchmarkResult.created_at)
                )
            )
            .scalars()
            .all()
        )

    return {
        "id": run.id,
        "name": run.name,
        "prompt_version": run.prompt_version,
        "model_config": run.model_config_json,
        "dataset_path": run.dataset_path,
        "triggered_by": run.triggered_by,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "totals": run.totals_json,
        "cases": [
            {
                "id": r.id,
                "case_id": r.case_id,
                "review_id": r.review_id,
                "expected_findings": r.expected_findings,
                "predicted_findings": r.predicted_findings,
                "true_positives": r.true_positives,
                "false_positives": r.false_positives,
                "false_negatives": r.false_negatives,
                "total_tokens": r.total_tokens,
                "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
                "cost_per_tp_usd": float(r.cost_per_tp_usd)
                if r.cost_per_tp_usd is not None
                else None,
                "stage_timings": r.stage_timings_json,
                "precision": r.true_positives / (r.true_positives + r.false_positives)
                if (r.true_positives + r.false_positives) > 0
                else None,
                "recall": r.true_positives / (r.true_positives + r.false_negatives)
                if (r.true_positives + r.false_negatives) > 0
                else None,
            }
            for r in results
        ],
    }


@router.get("/compare")
async def compare_benchmark_runs(
    run_a: int = Query(..., description="First run ID"),
    run_b: int = Query(..., description="Second run ID (baseline)"),
) -> dict[str, Any]:
    """Side-by-side comparison of two benchmark runs."""
    async with AsyncSessionLocal() as session:
        run_a_row = await session.get(BenchmarkRun, run_a)
        run_b_row = await session.get(BenchmarkRun, run_b)
        if run_a_row is None or run_b_row is None:
            raise HTTPException(status_code=404, detail="One or both benchmark runs not found")

        totals_a = run_a_row.totals_json or {}
        totals_b = run_b_row.totals_json or {}

    def _safe_delta(a: Any, b: Any) -> float | None:
        if a is None or b is None:
            return None
        try:
            return float(a) - float(b)
        except (TypeError, ValueError):
            return None

    return {
        "run_a": {
            "id": run_a,
            "name": run_a_row.name,
            "prompt_version": run_a_row.prompt_version,
            "totals": totals_a,
        },
        "run_b": {
            "id": run_b,
            "name": run_b_row.name,
            "prompt_version": run_b_row.prompt_version,
            "totals": totals_b,
        },
        "delta": {
            "precision": _safe_delta(totals_a.get("precision"), totals_b.get("precision")),
            "recall": _safe_delta(totals_a.get("recall"), totals_b.get("recall")),
            "false_positive_rate": _safe_delta(
                totals_a.get("false_positive_rate"), totals_b.get("false_positive_rate")
            ),
            "cost_usd": _safe_delta(totals_a.get("cost_usd"), totals_b.get("cost_usd")),
        },
    }


# ---------------------------------------------------------------------------
# Production telemetry endpoint (lives here rather than router.py for grouping)
# ---------------------------------------------------------------------------

telemetry_router = APIRouter(prefix="/api/v1/telemetry", dependencies=[Depends(_verify_api_access)])


@telemetry_router.get("/cost-per-finding")
async def cost_per_finding(
    installation_id: int | None = Query(default=None),
    model: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """
    Production cost-effectiveness: cost_usd / count(true-positive findings) per review.
    Joins reviews → finding_outcomes where outcome signals user acceptance.
    """
    POSITIVE_OUTCOMES = ("applied_directly", "applied_modified")

    async with AsyncSessionLocal() as session:
        tp_subq = (
            select(
                FindingOutcome.review_id,
                func.count(FindingOutcome.id).label("tp_count"),
            )
            .where(FindingOutcome.outcome.in_(POSITIVE_OUTCOMES))
            .group_by(FindingOutcome.review_id)
            .subquery()
        )

        q = (
            select(
                Review.id,
                Review.repo_full_name,
                Review.model_provider,
                Review.model,
                Review.cost_usd,
                Review.tokens_used,
                Review.completed_at,
                tp_subq.c.tp_count,
            )
            .join(tp_subq, Review.id == tp_subq.c.review_id)
            .where(Review.cost_usd.is_not(None))
            .order_by(Review.completed_at.desc())
            .limit(limit)
        )
        if installation_id is not None:
            q = q.where(Review.installation_id == installation_id)
        if model is not None:
            q = q.where(Review.model == model)

        rows = (await session.execute(q)).all()

    results = []
    total_cost = Decimal(0)
    total_tp = 0
    for row in rows:
        cost = Decimal(str(row.cost_usd)) if row.cost_usd is not None else None
        tp = int(row.tp_count)
        cost_per_tp = float(cost / tp) if cost and tp > 0 else None
        if cost:
            total_cost += cost
        total_tp += tp
        results.append(
            {
                "review_id": row.id,
                "repo_full_name": row.repo_full_name,
                "model_provider": row.model_provider,
                "model": row.model,
                "cost_usd": float(cost) if cost else None,
                "tokens_used": row.tokens_used,
                "true_positive_findings": tp,
                "cost_per_tp_usd": cost_per_tp,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            }
        )

    overall_cost_per_tp = float(total_cost / total_tp) if total_tp > 0 else None
    return {
        "summary": {
            "total_cost_usd": float(total_cost),
            "total_true_positives": total_tp,
            "overall_cost_per_tp_usd": overall_cost_per_tp,
            "reviews_analyzed": len(results),
        },
        "reviews": results,
    }
