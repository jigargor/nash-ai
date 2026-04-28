from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.agent.external.github_public import (
    PublicRepoError,
    PublicRepoRef,
    list_repo_files,
    resolve_repo_ref,
)
from app.agent.external.analyzer import analyze_file_content
from app.agent.external.prepass import run_prepass
from app.agent.external.planner import recommended_model_distribution, recommended_team_size
from app.agent.external.sharding import assign_shards
from app.agent.external.synthesis import ExternalCriticalFinding, dedupe_findings, is_critical_finding
from app.db.models import (
    ExternalEvaluation,
    ExternalEvaluationFinding,
    ExternalEvaluationShard,
)
from app.db.session import AsyncSessionLocal, set_installation_context
from sqlalchemy import func, select


def _estimate_shard_cost(file_count: int) -> tuple[int, Decimal]:
    estimated_tokens = max(file_count * 120, 400)
    estimated_cost = (Decimal(estimated_tokens) / Decimal(1_000_000)) * Decimal("0.15")
    return estimated_tokens, estimated_cost.quantize(Decimal("0.000001"))


async def _load_eval(eval_id: int) -> ExternalEvaluation | None:
    async with AsyncSessionLocal() as session:
        evaluation = await session.get(ExternalEvaluation, eval_id)
        if evaluation is None:
            return None
        await set_installation_context(session, int(evaluation.installation_id))
        return evaluation


async def run_external_eval_prepass(*, eval_id: int, redis: Any | None = None) -> None:
    async with AsyncSessionLocal() as session:
        evaluation = await session.get(ExternalEvaluation, eval_id)
        if evaluation is None:
            return
        await set_installation_context(session, int(evaluation.installation_id))
        evaluation.status = "scanning"
        evaluation.started_at = datetime.now(timezone.utc)
        await session.commit()

    evaluation = await _load_eval(eval_id)
    if evaluation is None:
        return
    try:
        repo_ref = await resolve_repo_ref(evaluation.owner, evaluation.repo, evaluation.target_ref)
        files = await list_repo_files(repo_ref)
    except PublicRepoError:
        async with AsyncSessionLocal() as session:
            evaluation = await session.get(ExternalEvaluation, eval_id)
            if evaluation is None:
                return
            await set_installation_context(session, int(evaluation.installation_id))
            evaluation.status = "failed"
            evaluation.summary = "Failed to resolve repository or target ref."
            evaluation.completed_at = datetime.now(timezone.utc)
            await session.commit()
        return

    signals, plan = await run_prepass(
        repo_ref_owner=repo_ref.owner,
        repo_ref_repo=repo_ref.repo,
        repo_ref_ref=repo_ref.ref,
        files=files,
    )
    shards = assign_shards(files, plan.shard_count)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        evaluation = await session.get(ExternalEvaluation, eval_id)
        if evaluation is None:
            return
        await set_installation_context(session, int(evaluation.installation_id))
        evaluation.status = "analyzing"
        evaluation.prepass_metadata = {
            "cheap_pass_model": plan.cheap_pass_model,
            "service_tier": plan.service_tier,
            "notes": plan.notes,
            "recommended_team_size": recommended_team_size(plan),
            "recommended_model_distribution": recommended_model_distribution(plan),
            "prompt_injection_paths": signals.prompt_injection_paths[:200],
            "filler_paths": signals.filler_paths[:200],
            "risky_paths": signals.risky_paths[:300],
            "ignored_paths_count": len(signals.ignored_paths),
            "file_count": len(files),
            "target_ref": repo_ref.ref,
        }
        evaluation.estimated_tokens = max(len(files) * 220, 800)
        evaluation.estimated_cost_usd = float(
            (Decimal(evaluation.estimated_tokens) * Decimal("0.00000015")).quantize(Decimal("0.000001"))
        )

        shard_rows: list[ExternalEvaluationShard] = []
        for shard_key, shard_files in shards.items():
            shard_rows.append(
                ExternalEvaluationShard(
                    external_evaluation_id=evaluation.id,
                    installation_id=evaluation.installation_id,
                    shard_key=shard_key,
                    model_tier=plan.service_tier,
                    file_count=len(shard_files),
                    meta_json={
                        "paths": [descriptor.path for descriptor in shard_files],
                        "sampled_at": now.isoformat(),
                    },
                    status="queued",
                )
            )
        session.add_all(shard_rows)
        await session.commit()

    if redis is None:
        return
    for shard_key in shards:
        async with AsyncSessionLocal() as session:
            evaluation = await session.get(ExternalEvaluation, eval_id)
            if evaluation is None:
                continue
            await set_installation_context(session, int(evaluation.installation_id))
            shard_row = await session.scalar(
                select(ExternalEvaluationShard).where(
                    ExternalEvaluationShard.external_evaluation_id == eval_id,
                    ExternalEvaluationShard.shard_key == shard_key,
                )
            )
            if shard_row is None:
                continue
            await redis.enqueue_job("external_eval_shard", int(shard_row.id))


async def run_external_eval_shard(*, shard_id: int, redis: Any | None = None) -> None:
    async with AsyncSessionLocal() as session:
        shard = await session.get(ExternalEvaluationShard, shard_id)
        if shard is None:
            return
        await set_installation_context(session, int(shard.installation_id))
        evaluation = await session.get(ExternalEvaluation, int(shard.external_evaluation_id))
        if evaluation is None:
            return
        shard.status = "running"
        shard.started_at = datetime.now(timezone.utc)
        await session.commit()

    async with AsyncSessionLocal() as session:
        shard = await session.get(ExternalEvaluationShard, shard_id)
        if shard is None:
            return
        await set_installation_context(session, int(shard.installation_id))
        evaluation = await session.get(ExternalEvaluation, int(shard.external_evaluation_id))
        if evaluation is None:
            return
        path_values = shard.meta_json.get("paths", []) if isinstance(shard.meta_json, dict) else []
        estimated_tokens, estimated_cost = _estimate_shard_cost(
            len(path_values) if isinstance(path_values, list) else 0
        )
        used_totals = await session.execute(
            select(
                func.coalesce(func.sum(ExternalEvaluationShard.tokens_used), 0),
                func.coalesce(func.sum(ExternalEvaluationShard.cost_usd), 0),
            ).where(
                ExternalEvaluationShard.external_evaluation_id == shard.external_evaluation_id,
                ExternalEvaluationShard.status.in_(["done", "synthesized"]),
            )
        )
        used_tokens, used_cost = used_totals.one()
        if int(used_tokens or 0) + estimated_tokens > int(evaluation.token_budget_cap) or Decimal(
            str(used_cost or 0)
        ) + estimated_cost > Decimal(str(evaluation.cost_budget_cap_usd)):
            shard.status = "skipped"
            shard.completed_at = datetime.now(timezone.utc)
            shard.meta_json = {
                **(shard.meta_json if isinstance(shard.meta_json, dict) else {}),
                "skip_reason": "budget_cap_reached",
            }
            await session.commit()
            return
        repo_ref = PublicRepoRef(
            owner=evaluation.owner,
            repo=evaluation.repo,
            ref=evaluation.target_ref,
            default_branch=evaluation.target_ref,
        )
        findings: list[ExternalCriticalFinding] = []
        if isinstance(path_values, list):
            from app.agent.external.github_public import fetch_file_sample

            for raw_path in path_values[:200]:
                if not isinstance(raw_path, str):
                    continue
                sample = await fetch_file_sample(repo_ref, raw_path, max_bytes=6000)
                if not sample:
                    continue
                analyzed = analyze_file_content(raw_path, sample)
                for candidate in analyzed:
                    finding: ExternalCriticalFinding = {
                        "category": candidate.category,
                        "severity": candidate.severity,
                        "title": candidate.title,
                        "message": candidate.message,
                        "file_path": candidate.file_path,
                        "line_start": candidate.line_start,
                        "line_end": candidate.line_end,
                        "evidence": candidate.evidence,
                    }
                    if is_critical_finding(finding):
                        findings.append(finding)

        shard.tokens_used = estimated_tokens
        shard.cost_usd = float(estimated_cost)
        shard.findings_count = len(findings)
        shard.status = "done"
        shard.completed_at = datetime.now(timezone.utc)

        for finding in findings:
            session.add(
                ExternalEvaluationFinding(
                    external_evaluation_id=shard.external_evaluation_id,
                    installation_id=shard.installation_id,
                    category=finding["category"],
                    severity=finding["severity"],
                    title=finding["title"],
                    message=finding["message"],
                    file_path=finding["file_path"],
                    line_start=finding["line_start"],
                    line_end=finding["line_end"],
                    evidence=finding["evidence"],
                )
            )
        await session.commit()

    if redis is None:
        return
    async with AsyncSessionLocal() as session:
        shard = await session.get(ExternalEvaluationShard, shard_id)
        if shard is None:
            return
        await set_installation_context(session, int(shard.installation_id))
        pending = await session.scalar(
            select(func.count(ExternalEvaluationShard.id)).where(
                ExternalEvaluationShard.external_evaluation_id == shard.external_evaluation_id,
                ExternalEvaluationShard.status.in_(["queued", "running"]),
            )
        )
        if int(pending or 0) == 0:
            await redis.enqueue_job("external_eval_synthesize", int(shard.external_evaluation_id))


async def run_external_eval_synthesize(*, eval_id: int) -> None:
    async with AsyncSessionLocal() as session:
        evaluation = await session.get(ExternalEvaluation, eval_id)
        if evaluation is None:
            return
        await set_installation_context(session, int(evaluation.installation_id))
        evaluation.status = "synthesizing"
        await session.commit()

    async with AsyncSessionLocal() as session:
        evaluation = await session.get(ExternalEvaluation, eval_id)
        if evaluation is None:
            return
        await set_installation_context(session, int(evaluation.installation_id))
        rows = await session.scalars(
            select(ExternalEvaluationFinding).where(
                ExternalEvaluationFinding.external_evaluation_id == eval_id
            )
        )
        raw_findings: list[ExternalCriticalFinding] = []
        for row in rows:
            raw_findings.append(
                {
                    "category": row.category,
                    "severity": row.severity,
                    "title": row.title,
                    "message": row.message,
                    "file_path": row.file_path,
                    "line_start": row.line_start,
                    "line_end": row.line_end,
                    "evidence": row.evidence if isinstance(row.evidence, dict) else {},
                }
            )
        deduped = dedupe_findings([finding for finding in raw_findings if is_critical_finding(finding)])
        evaluation.findings_count = len(deduped)
        skipped_count = await session.scalar(
            select(func.count(ExternalEvaluationShard.id)).where(
                ExternalEvaluationShard.external_evaluation_id == eval_id,
                ExternalEvaluationShard.status == "skipped",
            )
        )
        shard_totals = await session.execute(
            select(
                func.coalesce(func.sum(ExternalEvaluationShard.tokens_used), 0),
                func.coalesce(func.sum(ExternalEvaluationShard.cost_usd), 0),
            ).where(ExternalEvaluationShard.external_evaluation_id == eval_id)
        )
        tokens_sum, cost_sum = shard_totals.one()
        evaluation.tokens_used = int(tokens_sum or 0)
        evaluation.cost_usd = float(cost_sum or 0)
        evaluation.summary = (
            f"Completed external evaluation with {len(deduped)} critical findings."
            if deduped
            else "Completed external evaluation with no critical findings."
        )
        evaluation.status = "partial" if int(skipped_count or 0) > 0 else "complete"
        evaluation.completed_at = datetime.now(timezone.utc)
        await session.commit()

