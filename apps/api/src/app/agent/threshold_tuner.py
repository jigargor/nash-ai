from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import redis.exceptions as redis_exc
from redis.asyncio import Redis
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.review_config import AdaptiveThresholdConfig
from app.config import settings
from app.db.models import FastPathThresholdConfig, FastPathThresholdHistory, ReviewModelAudit
from app.db.session import AsyncSessionLocal, set_installation_context
from app.telemetry.finding_outcomes import summarize_finding_outcomes

logger = logging.getLogger(__name__)

THRESHOLD_CACHE_TTL_SECONDS = 60
THRESHOLD_CACHE_PREFIX = "fast-path-threshold"


@dataclass
class ThresholdTuningResult:
    installation_id: int
    previous_threshold: int
    current_threshold: int
    disagreement_rate: float
    dismiss_rate: float
    false_accept_rate: float
    sample_size: int
    action: str


def decide_next_threshold(
    *,
    previous_threshold: int,
    minimum_threshold: int,
    step_down: int,
    target_disagreement_low: int,
    target_disagreement_high: int,
    max_false_accept_rate: int,
    max_dismiss_rate: int,
    disagreement_rate: float,
    dismiss_rate: float,
    false_accept_rate: float,
    sample_size: int,
    min_samples: int,
) -> tuple[int, str]:
    if sample_size < min_samples:
        return previous_threshold, "hold_low_sample"

    high_disagreement = disagreement_rate > (target_disagreement_high / 100.0)
    low_disagreement = disagreement_rate < (target_disagreement_low / 100.0)
    excessive_false_accept = false_accept_rate > (max_false_accept_rate / 100.0)
    excessive_dismiss = dismiss_rate > (max_dismiss_rate / 100.0)
    if disagreement_rate >= 0.40 or excessive_false_accept or excessive_dismiss:
        return min(100, previous_threshold + step_down), "raise_or_rollback_guardrail"
    if low_disagreement:
        return max(minimum_threshold, previous_threshold - step_down), "lower_threshold"
    if high_disagreement:
        return min(100, previous_threshold + step_down), "raise_threshold"
    return previous_threshold, "hold_healthy_range"


def _cache_key(installation_id: int) -> str:
    return f"{THRESHOLD_CACHE_PREFIX}:{installation_id}"


async def get_effective_fast_path_threshold(
    installation_id: int, config: AdaptiveThresholdConfig
) -> int:
    cached = await _get_cached_threshold(installation_id)
    if cached is not None:
        return cached
    try:
        async with AsyncSessionLocal() as session:
            await set_installation_context(session, installation_id)
            row = await session.scalar(
                select(FastPathThresholdConfig).where(
                    FastPathThresholdConfig.installation_id == installation_id
                )
            )
            if row is None:
                threshold = int(config.initial_threshold)
            else:
                threshold = int(row.current_threshold)
    except Exception:
        logger.warning(
            "Falling back to default fast-path threshold installation_id=%s", installation_id
        )
        threshold = int(config.initial_threshold)
    await _set_cached_threshold(installation_id, threshold)
    return threshold


async def tune_fast_path_threshold(
    installation_id: int, config: AdaptiveThresholdConfig
) -> ThresholdTuningResult:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        row = await session.scalar(
            select(FastPathThresholdConfig).where(
                FastPathThresholdConfig.installation_id == installation_id
            )
        )
        if row is None:
            row = FastPathThresholdConfig(
                installation_id=installation_id,
                current_threshold=int(config.initial_threshold),
                minimum_threshold=int(config.minimum_threshold),
                step_down=int(config.step_down),
                target_disagreement_low=int(config.target_disagreement_low),
                target_disagreement_high=int(config.target_disagreement_high),
                max_false_accept_rate=int(config.max_false_accept_rate),
                max_dismiss_rate=int(config.max_dismiss_rate),
                min_samples=int(config.min_samples),
            )
            session.add(row)
            await session.flush()

        previous_threshold = int(row.current_threshold)
        disagreement_rate, sample_size = await _disagreement_rate(session, installation_id)
        summary = await summarize_finding_outcomes(installation_id=installation_id)
        global_metrics = summary.get("global_metrics", {})
        dismiss_rate = float(global_metrics.get("dismiss_rate", 0.0) or 0.0)
        # In this pipeline, dismissed+ignored are a practical proxy for false accepts.
        false_accept_rate = dismiss_rate + float(global_metrics.get("ignore_rate", 0.0) or 0.0)

        new_threshold, action = decide_next_threshold(
            previous_threshold=previous_threshold,
            minimum_threshold=int(row.minimum_threshold),
            step_down=int(row.step_down),
            target_disagreement_low=int(row.target_disagreement_low),
            target_disagreement_high=int(row.target_disagreement_high),
            max_false_accept_rate=int(row.max_false_accept_rate),
            max_dismiss_rate=int(row.max_dismiss_rate),
            disagreement_rate=disagreement_rate,
            dismiss_rate=dismiss_rate,
            false_accept_rate=false_accept_rate,
            sample_size=sample_size,
            min_samples=int(row.min_samples),
        )

        row.current_threshold = int(new_threshold)
        row.updated_at = datetime.now(timezone.utc)
        session.add(
            FastPathThresholdHistory(
                installation_id=installation_id,
                previous_threshold=previous_threshold,
                new_threshold=int(new_threshold),
                disagreement_rate=disagreement_rate,
                dismiss_rate=dismiss_rate,
                false_accept_rate=false_accept_rate,
                sample_size=sample_size,
                action=action,
            )
        )
        await session.commit()

    await _set_cached_threshold(installation_id, int(new_threshold))
    return ThresholdTuningResult(
        installation_id=installation_id,
        previous_threshold=previous_threshold,
        current_threshold=int(new_threshold),
        disagreement_rate=disagreement_rate,
        dismiss_rate=dismiss_rate,
        false_accept_rate=false_accept_rate,
        sample_size=sample_size,
        action=action,
    )


async def tune_all_installations(config: AdaptiveThresholdConfig) -> list[ThresholdTuningResult]:
    async with AsyncSessionLocal() as session:
        installation_ids = [
            int(value)
            for value in await session.scalars(select(ReviewModelAudit.installation_id).distinct())
        ]
    results: list[ThresholdTuningResult] = []
    for installation_id in installation_ids:
        try:
            results.append(await tune_fast_path_threshold(installation_id, config))
        except Exception:
            logger.exception("Threshold tuning failed installation_id=%s", installation_id)
    return results


async def rollback_fast_path_threshold(installation_id: int) -> int | None:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        latest = await session.scalar(
            select(FastPathThresholdHistory)
            .where(FastPathThresholdHistory.installation_id == installation_id)
            .order_by(FastPathThresholdHistory.recorded_at.desc())
            .limit(1)
        )
        if latest is None:
            return None
        row = await session.scalar(
            select(FastPathThresholdConfig).where(
                FastPathThresholdConfig.installation_id == installation_id
            )
        )
        if row is None:
            return None
        row.current_threshold = int(latest.previous_threshold)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
    await _set_cached_threshold(installation_id, int(latest.previous_threshold))
    return int(latest.previous_threshold)


async def _disagreement_rate(session: AsyncSession, installation_id: int) -> tuple[float, int]:
    rows = await session.execute(
        select(
            func.count(ReviewModelAudit.id),
            func.coalesce(func.sum(case((ReviewModelAudit.conflict_score > 0, 1), else_=0)), 0),
        )
        .where(ReviewModelAudit.installation_id == installation_id)
        .where(ReviewModelAudit.stage.in_(["challenger", "tie_break", "final_post"]))
    )
    total, disagreements = rows.one()
    total_int = int(total or 0)
    disagreement_int = int(disagreements or 0)
    if total_int == 0:
        return 0.0, 0
    return disagreement_int / total_int, total_int


async def _get_cached_threshold(installation_id: int) -> int | None:
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        raw = await redis.get(_cache_key(installation_id))
        if raw is None:
            return None
        payload = json.loads(raw)
        value = int(payload.get("threshold"))
        if value < 0 or value > 100:
            return None
        return value
    except (redis_exc.RedisError, ValueError, json.JSONDecodeError):
        logger.warning("Threshold cache read failed installation_id=%s", installation_id)
        return None
    finally:
        await redis.aclose()


async def _set_cached_threshold(installation_id: int, threshold: int) -> None:
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.setex(
            _cache_key(installation_id),
            THRESHOLD_CACHE_TTL_SECONDS,
            json.dumps({"threshold": int(threshold)}),
        )
    except redis_exc.RedisError:
        logger.warning("Threshold cache write failed installation_id=%s", installation_id)
    finally:
        await redis.aclose()
