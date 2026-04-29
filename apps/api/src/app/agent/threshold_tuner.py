from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import redis.exceptions as redis_exc
from redis.asyncio import Redis
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.judge_feedback.contracts import JudgeGateMetrics
from app.agent.judge_feedback.policy_engine import authorize_threshold_lowering
from app.agent.review_config import AdaptiveThresholdConfig
from app.config import settings
from app.db.models import FastPathThresholdConfig, FastPathThresholdHistory, ReviewModelAudit
from app.db.session import AsyncSessionLocal, set_installation_context
from app.telemetry.finding_outcomes import summarize_finding_outcomes

logger = logging.getLogger(__name__)

THRESHOLD_CACHE_TTL_SECONDS = 60
THRESHOLD_CACHE_PREFIX = "fast-path-threshold"
JUDGE_WINDOW_CACHE_TTL_SECONDS = 24 * 60 * 60
JUDGE_WINDOW_CACHE_PREFIX = "judge-feedback-window"


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
    judge_metrics: JudgeGateMetrics | None = None,
    min_judge_samples: int = 40,
    max_judge_false_negative_rate: int = 15,
    max_judge_false_positive_rate: int = 25,
    max_judge_inconclusive_rate: int = 20,
    min_judge_reliability_for_lowering: int = 82,
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
        allow_lowering, reason = authorize_threshold_lowering(
            judge_metrics=judge_metrics,
            min_judge_samples=min_judge_samples,
            max_judge_false_negative_rate=max_judge_false_negative_rate,
            max_judge_false_positive_rate=max_judge_false_positive_rate,
            max_judge_inconclusive_rate=max_judge_inconclusive_rate,
            min_judge_reliability_for_lowering=min_judge_reliability_for_lowering,
        )
        if not allow_lowering:
            return previous_threshold, f"hold_judge_gate_{reason}"
        return max(minimum_threshold, previous_threshold - step_down), "lower_threshold"
    if high_disagreement:
        return min(100, previous_threshold + step_down), "raise_threshold"
    return previous_threshold, "hold_healthy_range"


def _cache_key(installation_id: int) -> str:
    return f"{THRESHOLD_CACHE_PREFIX}:{installation_id}"


def _judge_window_cache_key(installation_id: int) -> str:
    return f"{JUDGE_WINDOW_CACHE_PREFIX}:{installation_id}"


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
        global_metrics_raw = summary.get("global_metrics", {})
        global_metrics = global_metrics_raw if isinstance(global_metrics_raw, dict) else {}
        dismiss_rate = float(global_metrics.get("dismiss_rate", 0.0) or 0.0)
        # In this pipeline, dismissed+ignored are a practical proxy for false accepts.
        false_accept_rate = dismiss_rate + float(global_metrics.get("ignore_rate", 0.0) or 0.0)
        judge_metrics: JudgeGateMetrics | None = None
        if config.judge_feedback_enabled and not config.judge_collect_only:
            judge_metrics = await _load_judge_gate_metrics(
                session,
                installation_id,
                require_provider_family_differ=bool(config.judge_provider_family_must_differ),
            )

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
            judge_metrics=judge_metrics,
            min_judge_samples=int(config.min_judge_samples),
            max_judge_false_negative_rate=int(config.max_judge_false_negative_rate),
            max_judge_false_positive_rate=int(config.max_judge_false_positive_rate),
            max_judge_inconclusive_rate=int(config.max_judge_inconclusive_rate),
            min_judge_reliability_for_lowering=int(config.min_judge_reliability_for_lowering),
        )
        await publish_judge_gate_window(
            installation_id=installation_id,
            judge_metrics=judge_metrics,
            tuner_action=action,
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


async def refresh_judge_gate_windows(config: AdaptiveThresholdConfig) -> dict[str, object]:
    if not config.judge_feedback_enabled:
        return {"enabled": False, "updated": 0, "installation_ids": []}
    async with AsyncSessionLocal() as session:
        installation_ids = [
            int(value)
            for value in await session.scalars(select(ReviewModelAudit.installation_id).distinct())
        ]
    updated: list[int] = []
    for installation_id in installation_ids:
        try:
            await refresh_judge_gate_window_for_installation(
                installation_id,
                require_provider_family_differ=bool(config.judge_provider_family_must_differ),
            )
            updated.append(installation_id)
        except Exception:
            logger.exception(
                "Judge gate window refresh failed installation_id=%s", installation_id
            )
    return {"enabled": True, "updated": len(updated), "installation_ids": updated}


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


async def refresh_judge_gate_window_for_installation(
    installation_id: int, *, require_provider_family_differ: bool, lookback_days: int = 14
) -> dict[str, object]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        rows = (
            await session.scalars(
                select(ReviewModelAudit.metadata_json)
                .where(ReviewModelAudit.installation_id == installation_id)
                .where(ReviewModelAudit.stage == "judge_assessment")
                .where(ReviewModelAudit.created_at >= since)
                .order_by(ReviewModelAudit.created_at.desc())
                .limit(1000)
            )
        ).all()
    metadata_rows = [row for row in rows if isinstance(row, dict)]
    judge_metrics = _judge_metrics_from_assessment_rows(
        metadata_rows,
        require_provider_family_differ=require_provider_family_differ,
    )
    return await publish_judge_gate_window(
        installation_id=installation_id,
        judge_metrics=judge_metrics,
        extra={
            "source": "judge_assessment_aggregate",
            "lookback_days": int(max(1, lookback_days)),
            "assessment_row_count": len(metadata_rows),
        },
    )


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


async def _load_judge_gate_metrics(
    session: AsyncSession,
    installation_id: int,
    *,
    require_provider_family_differ: bool,
) -> JudgeGateMetrics:
    cached = await get_cached_judge_gate_window(installation_id)
    if isinstance(cached, dict):
        return _judge_metrics_from_metadata(
            cached, require_provider_family_differ=require_provider_family_differ
        )
    metadata = await session.scalar(
        select(ReviewModelAudit.metadata_json)
        .where(ReviewModelAudit.installation_id == installation_id)
        .where(ReviewModelAudit.stage == "judge_feedback_window")
        .order_by(ReviewModelAudit.created_at.desc())
        .limit(1)
    )
    if not isinstance(metadata, dict):
        return JudgeGateMetrics(is_available=False, provider_independent=False)
    return _judge_metrics_from_metadata(
        metadata, require_provider_family_differ=require_provider_family_differ
    )


def _judge_metrics_from_metadata(
    metadata: dict[str, object], *, require_provider_family_differ: bool
) -> JudgeGateMetrics:
    payload = metadata.get("judge_gate_metrics")
    source = payload if isinstance(payload, dict) else metadata

    provider_independent = _provider_independence_from_metadata(
        source, require_provider_family_differ=require_provider_family_differ
    )
    sample_size = _int_from_metadata(source.get("sample_size"))
    false_negative_rate = _float_from_metadata(source.get("false_negative_rate"))
    false_positive_rate = _float_from_metadata(source.get("false_positive_rate"))
    inconclusive_rate = _float_from_metadata(source.get("inconclusive_rate"))
    reliability_score = _float_from_metadata(source.get("reliability_score"))
    is_available_raw = source.get("is_available")
    is_available = (
        bool(is_available_raw)
        if isinstance(is_available_raw, bool)
        else sample_size > 0
        or false_negative_rate is not None
        or false_positive_rate is not None
        or inconclusive_rate is not None
        or reliability_score is not None
    )
    return JudgeGateMetrics(
        is_available=is_available,
        provider_independent=provider_independent,
        sample_size=sample_size,
        false_negative_rate=false_negative_rate,
        false_positive_rate=false_positive_rate,
        inconclusive_rate=inconclusive_rate,
        reliability_score=reliability_score,
    )


def _judge_metrics_from_assessment_rows(
    rows: list[dict[str, object]], *, require_provider_family_differ: bool
) -> JudgeGateMetrics:
    if not rows:
        return JudgeGateMetrics(is_available=False, provider_independent=False)
    sample_size = 0
    fn_count = 0
    fp_count = 0
    inconclusive_count = 0
    reliability_score: float | None = None
    provider_independent: bool | None = None
    for row in rows:
        quality_label = row.get("quality_label")
        if isinstance(quality_label, str):
            normalized = quality_label.strip().lower()
            if normalized in {
                "acceptable",
                "missed_material_issue",
                "posted_false_positive",
                "inconclusive",
            }:
                sample_size += 1
                if normalized == "missed_material_issue":
                    fn_count += 1
                elif normalized == "posted_false_positive":
                    fp_count += 1
                elif normalized == "inconclusive":
                    inconclusive_count += 1
        if reliability_score is None:
            reliability_score = _float_from_metadata(
                row.get("judge_reliability_score", row.get("reliability_score"))
            )
        if provider_independent is None:
            provider_independent = _provider_independence_from_metadata(
                row,
                require_provider_family_differ=require_provider_family_differ,
            )
    if sample_size <= 0:
        return JudgeGateMetrics(
            is_available=False,
            provider_independent=bool(provider_independent),
            sample_size=0,
            false_negative_rate=None,
            false_positive_rate=None,
            inconclusive_rate=None,
            reliability_score=reliability_score,
        )
    return JudgeGateMetrics(
        is_available=True,
        provider_independent=bool(provider_independent),
        sample_size=sample_size,
        false_negative_rate=fn_count / sample_size,
        false_positive_rate=fp_count / sample_size,
        inconclusive_rate=inconclusive_count / sample_size,
        reliability_score=reliability_score,
    )


def _provider_independence_from_metadata(
    source: dict[str, object], *, require_provider_family_differ: bool
) -> bool:
    explicit = source.get("provider_independent")
    if isinstance(explicit, bool):
        return explicit
    if not require_provider_family_differ:
        return True
    judge_family = source.get("judge_provider_family")
    primary_family = source.get("primary_provider_family")
    if isinstance(judge_family, str) and isinstance(primary_family, str):
        normalized_judge = judge_family.strip().lower()
        normalized_primary = primary_family.strip().lower()
        if normalized_judge and normalized_primary:
            return normalized_judge != normalized_primary
    return False


def _int_from_metadata(raw: object) -> int:
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, float):
        return max(0, int(raw))
    if isinstance(raw, str):
        try:
            return max(0, int(raw.strip()))
        except ValueError:
            return 0
    return 0


def _float_from_metadata(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            return None
    else:
        return None
    if value < 0.0:
        return None
    return value


async def _get_cached_judge_gate_window(installation_id: int) -> dict[str, object] | None:
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        raw = await redis.get(_judge_window_cache_key(installation_id))
        if raw is None:
            return None
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except (redis_exc.RedisError, ValueError, json.JSONDecodeError):
        logger.warning("Judge gate cache read failed installation_id=%s", installation_id)
    finally:
        await redis.aclose()
    return None


async def get_cached_judge_gate_window(installation_id: int) -> dict[str, object] | None:
    return await _get_cached_judge_gate_window(installation_id)


def _empty_judge_gate_metrics_payload() -> dict[str, object]:
    return {
        "is_available": False,
        "provider_independent": False,
        "sample_size": 0,
        "false_negative_rate": None,
        "false_positive_rate": None,
        "inconclusive_rate": None,
        "reliability_score": None,
    }


def _build_judge_gate_window_payload(
    *,
    judge_metrics: JudgeGateMetrics | None,
    tuner_action: str | None = None,
    recorded_at: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "judge_gate_metrics": (
            asdict(judge_metrics)
            if judge_metrics is not None
            else _empty_judge_gate_metrics_payload()
        ),
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
    }
    if tuner_action is not None and tuner_action.strip():
        payload["tuner_action"] = tuner_action.strip()
    if extra:
        payload.update(extra)
    return payload


async def publish_judge_gate_window(
    *,
    installation_id: int,
    judge_metrics: JudgeGateMetrics | None,
    tuner_action: str | None = None,
    recorded_at: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = _build_judge_gate_window_payload(
        judge_metrics=judge_metrics,
        tuner_action=tuner_action,
        recorded_at=recorded_at,
        extra=extra,
    )
    await _set_cached_judge_gate_window(installation_id, payload)
    return payload


async def _set_cached_judge_gate_window(installation_id: int, payload: dict[str, object]) -> None:
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.setex(
            _judge_window_cache_key(installation_id),
            JUDGE_WINDOW_CACHE_TTL_SECONDS,
            json.dumps(payload),
        )
    except redis_exc.RedisError:
        logger.warning("Judge gate cache write failed installation_id=%s", installation_id)
    finally:
        await redis.aclose()


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
