from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agent.offline_eval import replay_snapshot_to_review_result
from app.agent.schema import Finding, ReviewResult
from app.agent.snapshot import load_snapshot
from app.config import settings
from app.db.models import Review
from app.db.session import AsyncSessionLocal, set_installation_context

logger = logging.getLogger(__name__)


def should_enqueue_shadow_benchmark(review_id: int) -> bool:
    sample_rate = float(settings.review_benchmark_sample_rate)
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    digest = hashlib.sha256(str(review_id).encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return bucket <= sample_rate


async def run_shadow_benchmark(
    *,
    review_id: int,
    installation_id: int,
    control_run_id: str,
) -> None:
    snapshot = await load_snapshot(review_id)
    if snapshot is None:
        logger.info("Skipping shadow benchmark: snapshot missing review_id=%s", review_id)
        await _store_benchmark_artifact(
            review_id=review_id,
            installation_id=installation_id,
            payload={"status": "skipped", "reason": "snapshot_missing", "control_run_id": control_run_id},
        )
        return

    provider = _benchmark_provider()
    model_name = _default_model_for_provider(provider)
    started = datetime.now(timezone.utc)
    try:
        candidate = await replay_snapshot_to_review_result(
            {
                "review_id": snapshot.review_id,
                "pr_metadata": snapshot.pr_metadata,
                "diff_text": snapshot.diff_text,
                "system_prompt": snapshot.system_prompt,
                "user_prompt": snapshot.user_prompt,
                "fetched_files": snapshot.fetched_files,
            },
            model_name=model_name,
            provider=provider,
        )
        control = await _load_control_review_result(review_id, installation_id)
        overlap = _finding_overlap(control.findings, candidate.findings)
        await _store_benchmark_artifact(
            review_id=review_id,
            installation_id=installation_id,
            payload={
                "status": "done",
                "control_run_id": control_run_id,
                "candidate_provider": provider,
                "candidate_model": model_name,
                "started_at": started.isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "control_findings": len(control.findings),
                "candidate_findings": len(candidate.findings),
                "finding_overlap": overlap,
            },
        )
    except Exception as exc:  # pragma: no cover - best effort path
        logger.warning(
            "Shadow benchmark failed review_id=%s installation_id=%s err=%s",
            review_id,
            installation_id,
            exc,
        )
        await _store_benchmark_artifact(
            review_id=review_id,
            installation_id=installation_id,
            payload={
                "status": "failed",
                "control_run_id": control_run_id,
                "candidate_provider": provider,
                "candidate_model": model_name,
                "error": type(exc).__name__,
            },
        )


def _benchmark_provider() -> str:
    if settings.anthropic_api_key:
        return "anthropic"
    if settings.openai_api_key:
        return "openai"
    if settings.gemini_api_key:
        return "gemini"
    return "anthropic"


def _default_model_for_provider(provider: str) -> str:
    if provider == "openai":
        return settings.openai_default_model
    if provider == "gemini":
        return settings.gemini_default_model
    return settings.anthropic_default_model


def _finding_key(finding: Finding) -> tuple[str, int, str, str]:
    return (finding.file_path, finding.line_start, finding.severity, finding.category)


def _finding_overlap(control: list[Finding], candidate: list[Finding]) -> float:
    control_keys = {_finding_key(item) for item in control}
    candidate_keys = {_finding_key(item) for item in candidate}
    if not control_keys and not candidate_keys:
        return 1.0
    if not control_keys:
        return 0.0
    return len(control_keys.intersection(candidate_keys)) / len(control_keys)


async def _load_control_review_result(review_id: int, installation_id: int) -> ReviewResult:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = (
            await session.execute(select(Review).where(Review.id == review_id))
        ).scalar_one_or_none()
    if review is None or not isinstance(review.findings, dict):
        return ReviewResult(findings=[], summary="Control review missing.")
    return ReviewResult.model_validate(review.findings)


async def _store_benchmark_artifact(
    *,
    review_id: int,
    installation_id: int,
    payload: dict[str, Any],
) -> None:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = (
            await session.execute(select(Review).where(Review.id == review_id))
        ).scalar_one_or_none()
        if review is None:
            return
        artifacts = dict(review.debug_artifacts or {})
        artifacts["benchmark_shadow"] = payload
        review.debug_artifacts = artifacts
        await session.commit()
