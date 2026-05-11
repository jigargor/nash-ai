"""ARQ worker orchestration for external evaluations.

Thin adapter around :class:`ReviewEngine`:

* stage 1 (``run_external_eval_prepass``) — resolve repo, list files,
  run prepass, persist the plan and shards, enqueue shard jobs,
* stage 2 (``run_external_eval_shard``) — analyze a single shard and
  persist findings,
* stage 3 (``run_external_eval_synthesize``) — run the final synthesis
  pass over all shard findings and finalize the evaluation row.

Every database session is scoped to the target installation via RLS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.agent.external.planner import (
    recommended_model_distribution,
    recommended_team_size,
)
from app.agent.external.prepass import _fast_pass_model
from app.db.models import (
    ExternalEvaluation,
    ExternalEvaluationFinding,
    ExternalEvaluationShard,
)
from app.db.session import AsyncSessionLocal, set_installation_context
from app.review.external.engine import ReviewEngine
from app.review.external.errors import RepoAccessError
from app.review.external.models import (
    EngineConfig,
    Finding,
    RepoRef,
)
from app.review.external.sharding import build_shards
from app.review.external.sources.base import RepoSource
from app.review.external.sources.github import GitHubRepoSource
from app.review.external.synthesis import synthesize

_DEFAULT_PRICE_PER_1M_USD = 0.15


def _build_engine(source: RepoSource) -> ReviewEngine:
    return ReviewEngine(
        source=source,
        config=EngineConfig(price_per_1m_tokens_usd=_DEFAULT_PRICE_PER_1M_USD),
        cheap_pass_model_resolver=_fast_pass_model,
    )


def _estimate_shard_cost(
    file_count: int, *, price_per_1m_usd: float = _DEFAULT_PRICE_PER_1M_USD
) -> tuple[int, Decimal]:
    estimated_tokens = max(file_count * 120, 400)
    estimated_cost = (
        Decimal(estimated_tokens) / Decimal(1_000_000) * Decimal(str(price_per_1m_usd))
    )
    return estimated_tokens, estimated_cost.quantize(Decimal("0.000001"))


async def _load_eval(eval_id: int) -> ExternalEvaluation | None:
    async with AsyncSessionLocal() as session:
        evaluation = await session.get(ExternalEvaluation, eval_id)
        if evaluation is None:
            return None
        await set_installation_context(session, int(evaluation.installation_id))
        return evaluation


async def run_external_eval_prepass(
    *, eval_id: int, redis: Any | None = None
) -> None:
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

    async with GitHubRepoSource() as source:
        engine = _build_engine(source)
        try:
            repo_ref = await source.resolve_ref(
                evaluation.owner, evaluation.repo, evaluation.target_ref
            )
            files = await source.list_files(
                repo_ref, max_files=engine.config.max_files
            )
            signals, plan = await engine.prepass(repo_ref, files)
        except RepoAccessError:
            async with AsyncSessionLocal() as session:
                evaluation = await session.get(ExternalEvaluation, eval_id)
                if evaluation is None:
                    return
                await set_installation_context(
                    session, int(evaluation.installation_id)
                )
                evaluation.status = "failed"
                evaluation.summary = "Failed to resolve repository or target ref."
                evaluation.completed_at = datetime.now(timezone.utc)
                await session.commit()
            return

    excluded = set(signals.prompt_injection_paths) | set(signals.filler_paths)
    shards = build_shards(
        files,
        shard_count=plan.shard_count,
        excluded_paths=excluded,
    )
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
            "notes": list(plan.notes),
            "recommended_team_size": recommended_team_size(plan),
            "recommended_model_distribution": recommended_model_distribution(plan),
            "prompt_injection_paths": signals.prompt_injection_paths[:200],
            "filler_paths": signals.filler_paths[:200],
            "risky_paths": signals.risky_paths[:300],
            "ignored_paths_count": signals.ignored_paths_count,
            "file_count": len(files),
            "target_ref": repo_ref.ref,
            "estimated_tokens": int(evaluation.estimated_tokens),
            "estimated_cost_usd": str(evaluation.estimated_cost_usd),
        }

        shard_rows: list[ExternalEvaluationShard] = []
        path_lookup = {descriptor.path: descriptor for descriptor in files}
        for shard in shards:
            shard_rows.append(
                ExternalEvaluationShard(
                    external_evaluation_id=evaluation.id,
                    installation_id=evaluation.installation_id,
                    shard_key=shard.shard_key,
                    model_tier=plan.service_tier,
                    file_count=len(shard.paths),
                    meta_json={
                        "paths": [
                            path
                            for path in shard.paths
                            if path in path_lookup
                        ],
                        "sampled_at": now.isoformat(),
                    },
                    status="queued",
                )
            )
        session.add_all(shard_rows)
        await session.commit()

    if redis is None:
        return
    for shard in shards:
        async with AsyncSessionLocal() as session:
            evaluation = await session.get(ExternalEvaluation, eval_id)
            if evaluation is None:
                continue
            await set_installation_context(
                session, int(evaluation.installation_id)
            )
            shard_row = await session.scalar(
                select(ExternalEvaluationShard).where(
                    ExternalEvaluationShard.external_evaluation_id == eval_id,
                    ExternalEvaluationShard.shard_key == shard.shard_key,
                )
            )
            if shard_row is None:
                continue
            await redis.enqueue_job("external_eval_shard", int(shard_row.id))


async def run_external_eval_shard(
    *, shard_id: int, redis: Any | None = None
) -> None:
    async with AsyncSessionLocal() as session:
        shard = await session.get(ExternalEvaluationShard, shard_id)
        if shard is None:
            return
        await set_installation_context(session, int(shard.installation_id))
        evaluation = await session.get(
            ExternalEvaluation, int(shard.external_evaluation_id)
        )
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
        evaluation = await session.get(
            ExternalEvaluation, int(shard.external_evaluation_id)
        )
        if evaluation is None:
            return
        path_values = (
            shard.meta_json.get("paths", [])
            if isinstance(shard.meta_json, dict)
            else []
        )
        estimated_tokens, estimated_cost = _estimate_shard_cost(
            len(path_values) if isinstance(path_values, list) else 0
        )
        used_totals = await session.execute(
            select(
                func.coalesce(func.sum(ExternalEvaluationShard.tokens_used), 0),
                func.coalesce(func.sum(ExternalEvaluationShard.cost_usd), 0),
            ).where(
                ExternalEvaluationShard.external_evaluation_id
                == shard.external_evaluation_id,
                ExternalEvaluationShard.status.in_(["done", "synthesized"]),
            )
        )
        used_tokens, used_cost = used_totals.one()
        if int(used_tokens or 0) + estimated_tokens > int(
            evaluation.token_budget_cap
        ) or Decimal(str(used_cost or 0)) + estimated_cost > Decimal(
            str(evaluation.cost_budget_cap_usd)
        ):
            shard.status = "skipped"
            shard.completed_at = datetime.now(timezone.utc)
            shard.meta_json = {
                **(shard.meta_json if isinstance(shard.meta_json, dict) else {}),
                "skip_reason": "budget_cap_reached",
            }
            await session.commit()
            return
        repo_ref = RepoRef(
            owner=evaluation.owner,
            repo=evaluation.repo,
            ref=evaluation.target_ref,
            default_branch=evaluation.target_ref,
        )
        findings: list[Finding] = []
        async with GitHubRepoSource() as source:
            engine = _build_engine(source)
            from app.review.external.models import Shard  # local import to avoid cycles

            shard_model = Shard(
                shard_key=shard.shard_key,
                paths=tuple(
                    path for path in (path_values or []) if isinstance(path, str)
                )[: engine.config.max_analyze_files_per_shard],
            )
            result = await engine.analyze_shard(repo_ref, shard_model)
            for finding in result.findings:
                if synthesize([finding]):
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
                    category=finding.category,
                    severity=finding.severity,
                    title=finding.title,
                    message=finding.message,
                    file_path=finding.file_path,
                    line_start=finding.line_start,
                    line_end=finding.line_end,
                    evidence=dict(finding.evidence),
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
                ExternalEvaluationShard.external_evaluation_id
                == shard.external_evaluation_id,
                ExternalEvaluationShard.status.in_(["queued", "running"]),
            )
        )
        if int(pending or 0) == 0:
            await redis.enqueue_job(
                "external_eval_synthesize",
                int(shard.external_evaluation_id),
            )


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
        raw_findings: list[Finding] = []
        for row in rows:
            try:
                raw_findings.append(
                    Finding(
                        category=row.category,  # type: ignore[arg-type]
                        severity=row.severity,  # type: ignore[arg-type]
                        title=row.title,
                        message=row.message,
                        file_path=row.file_path or "",
                        line_start=int(row.line_start or 1),
                        line_end=row.line_end,
                        evidence=row.evidence
                        if isinstance(row.evidence, dict)
                        else {},
                    )
                )
            except ValueError:
                continue
        deduped = synthesize(raw_findings)
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
        evaluation.status = (
            "partial" if int(skipped_count or 0) > 0 else "complete"
        )
        evaluation.completed_at = datetime.now(timezone.utc)
        await session.commit()
