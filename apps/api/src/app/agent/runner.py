import logging
import json
from dataclasses import replace
from hashlib import sha256
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from fnmatch import fnmatch
from time import monotonic
from typing import Any, TypedDict, cast
from uuid import uuid4

import redis.exceptions as redis_exc
from pydantic import ValidationError
from redis.asyncio import Redis

from app.agent.acknowledgments import extract_todo_fixme_markers
from app.agent.config_cache import get_cached_review_config, set_cached_review_config
from app.agent.constants import PROMPT_VERSION, REPAIR_RETRY_DROP_RATE, REPAIR_SEARCH_WINDOW
from app.agent.chunking import ClassifiedDiffFile, ChunkPlan, ChunkingPlannerConfig, FileClass, PlannedChunk, plan_chunks
from app.agent.chunked_runtime import (
    chunk_repo_segments,
    chunk_status,
    load_chunk_state,
    merge_chunk_state_with_plan,
    persist_chunk_state,
    render_chunk_diff,
)
from app.agent.context_builder import (
    ContextBundle,
    ContextTelemetry,
    build_context_bundle,
    count_tokens,
    is_diff_too_large,
)
from app.agent.diff_parser import FileInDiff, parse_diff, right_side_diff_line_set
from app.agent.anchors import attach_anchor_metadata, filter_findings_with_valid_anchors
from app.agent.dedupe import dedupe_findings
from app.agent.editor import run_editor
from app.agent.finalize import finalize_review
from app.agent.fast_path import (
    FastPathDecision,
    fallback_full_review,
    fast_path_metadata,
    run_fast_path_prepass,
)
from app.agent.loop import run_agent
from app.agent.normalization import normalize_for_match
from app.agent.profiler import profile_repo
from app.agent.prompts import build_initial_user_prompt, build_system_prompt, load_verified_fact_ids
from app.agent.review_config import ReviewConfig, load_review_config
from app.agent.schema import DropReason, EditedReview, Finding, ReviewResult
from app.agent.validator import FindingValidator
from app.agent.vendor_detect import auto_tag_vendor_claims
from app.config import settings
from app.db.models import Review, ReviewModelAudit
from app.db.session import AsyncSessionLocal, set_installation_context
from app.github.client import GitHubClient
from app.github.comments import post_review
from app.llm.router import ModelResolution, ReviewModelRole, resolve_model_for_role
from app.llm.router import ModelRoleRoutingConfig
from app.llm.types import ModelProvider
from app.observability import record_review_trace
from app.ratelimit import check_and_consume_daily_token_budget, current_daily_token_usage
from app.telemetry.finding_outcomes import seed_pending_finding_outcomes

logger = logging.getLogger(__name__)
FULL_REGENERATE_RETRY_DROP_RATE = 0.50
MIN_RECOVERY_RATIO_FOR_SUCCESS = 0.50
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ALLOWED_CHUNK_FILE_CLASSES: set[FileClass] = {
    "reviewable",
    "generated",
    "lockfile",
    "test_only",
    "config_only",
    "docs_only",
    "binary_unsupported",
    "deleted_only",
}


class DiffAnchorMetadata(TypedDict):
    new_line_no: int | None
    old_line_no: int | None
    hunk_id: str


async def _mark_review_running(review_id: int, installation_id: int) -> None:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise RuntimeError(f"Review {review_id} does not exist")
        review.status = "running"
        review.started_at = datetime.now(timezone.utc)
        await session.commit()


async def _fetch_pr_inputs(
    context: dict[str, Any],
) -> tuple["GitHubClient", str, dict[str, Any], list[dict[str, Any]], "ReviewConfig"]:
    owner: str = context["owner"]
    repo: str = context["repo"]
    pr_number: int = context["pr_number"]
    head_sha: str = context["head_sha"]
    installation_id: int = context["installation_id"]
    review_id: int = context["review_id"]

    gh = await GitHubClient.for_installation(installation_id)
    context["github_client"] = gh
    record_review_trace(
        {
            "review_id": review_id,
            "installation_id": installation_id,
            "repo": f"{owner}/{repo}",
            "pr_number": pr_number,
            "head_sha": head_sha,
            "run_id": context.get("run_id"),
        }
    )
    diff_text = await gh.get_pull_request_diff(owner, repo, pr_number)
    pr = await gh.get_pull_request(owner, repo, pr_number)
    commits = await gh.get_pull_request_commits(owner, repo, pr_number)
    review_config = await _load_review_config_cached(gh, owner, repo, head_sha)
    record_review_trace(
        {
            "review_id": review_id,
            "installation_id": installation_id,
            "repo": f"{owner}/{repo}",
            "pr_number": pr_number,
            "head_sha": head_sha,
            "run_id": context.get("run_id"),
            "model": review_config.model.name,
            "provider": review_config.model.provider,
            "prompt_version": PROMPT_VERSION,
        }
    )
    return gh, diff_text, pr, commits, review_config


async def _assemble_context(
    gh: "GitHubClient",
    context: dict[str, Any],
    diff_text: str,
    review_config: "ReviewConfig",
) -> "tuple[list[FileInDiff], dict[str, str], ContextBundle, str, str]":
    owner: str = context["owner"]
    repo: str = context["repo"]
    pr_number: int = context["pr_number"]
    head_sha: str = context["head_sha"]

    files_in_diff = _filter_diff_files(parse_diff(diff_text), review_config.ignore_paths)
    repo_profile = await profile_repo(gh, owner, repo, head_sha)
    repo_segments = _build_repo_segments(repo_profile.frameworks, review_config.prompt_additions)
    context_bundle = await build_context_bundle(
        gh,
        owner,
        repo,
        head_sha,
        files_in_diff,
        budgets=review_config.budgets,
        packaging=review_config.packaging,
        repo_segments=repo_segments,
    )
    fetched_map: dict[str, str] = dict(context_bundle.fetched_files)
    context["fetched_files"] = fetched_map
    context["frameworks"] = repo_profile.frameworks
    _warn_if_carriage_returns(fetched_map)
    system_prompt = build_system_prompt(repo_profile.frameworks, diff_text, review_config.prompt_additions)
    user_prompt = build_initial_user_prompt(owner, repo, pr_number, context_bundle.rendered)
    return files_in_diff, fetched_map, context_bundle, system_prompt, user_prompt


def _resolve_runtime_model(
    context: dict[str, Any],
    review_config: ReviewConfig,
    role: ReviewModelRole,
    *,
    context_tokens: int = 0,
    previous_provider: str | None = None,
) -> ModelResolution:
    resolution = resolve_model_for_role(
        review_config,
        role,
        context_tokens=context_tokens,
        previous_provider=previous_provider,
    )
    context.setdefault("llm_model_resolutions", {})
    resolutions = context.get("llm_model_resolutions")
    if isinstance(resolutions, dict):
        resolutions[role] = resolution.as_metadata()
    if role in {"primary_review", "chunk_review"}:
        context["runtime_model_provider"] = resolution.provider
        context["runtime_model"] = resolution.model
        context["runtime_input_per_1m_usd"] = str(resolution.input_per_1m_usd) if resolution.input_per_1m_usd is not None else None
        context["runtime_cached_input_per_1m_usd"] = (
            str(resolution.cached_input_per_1m_usd) if resolution.cached_input_per_1m_usd is not None else None
        )
        context["runtime_output_per_1m_usd"] = str(resolution.output_per_1m_usd) if resolution.output_per_1m_usd is not None else None
    context.setdefault("anthropic_cache_ttl", "5m")
    context.setdefault("openai_prompt_cache_retention", "in_memory")
    return resolution


def _set_runtime_model_context(context: dict[str, Any], resolution: ModelResolution) -> None:
    context["runtime_model_provider"] = resolution.provider
    context["runtime_model"] = resolution.model
    context["runtime_input_per_1m_usd"] = str(resolution.input_per_1m_usd) if resolution.input_per_1m_usd is not None else None
    context["runtime_cached_input_per_1m_usd"] = (
        str(resolution.cached_input_per_1m_usd) if resolution.cached_input_per_1m_usd is not None else None
    )
    context["runtime_output_per_1m_usd"] = str(resolution.output_per_1m_usd) if resolution.output_per_1m_usd is not None else None


async def _run_fast_path_stage(
    *,
    context: dict[str, Any],
    diff_text: str,
    pr: dict[str, Any],
    commits: list[dict[str, Any]],
    review_config: ReviewConfig,
    diff_tokens: int,
) -> tuple[FastPathDecision, ModelResolution | None]:
    if not review_config.fast_path.enabled:
        return fallback_full_review("Fast-path pre-pass is disabled.", risk_labels=["disabled"]), None

    files_in_diff = _filter_diff_files(parse_diff(diff_text), review_config.ignore_paths)
    fast_resolution = _resolve_runtime_model(
        context,
        review_config,
        "fast_path",
        context_tokens=min(diff_tokens, review_config.fast_path.max_diff_excerpt_tokens),
    )
    token_snapshot = _token_snapshot(context)
    classified: list[ClassifiedDiffFile] = []
    fallback_reason: str | None = fast_resolution.fallback_reason
    try:
        decision, classified, _, _ = await run_fast_path_prepass(
            files_in_diff=files_in_diff,
            diff_text=diff_text,
            pr=pr,
            commits=commits,
            generated_paths=review_config.packaging.generated_paths,
            vendor_paths=review_config.packaging.vendor_paths,
            config=review_config.fast_path,
            context=context,
            model_name=fast_resolution.model,
            provider=fast_resolution.provider,
        )
    except Exception as exc:
        logger.warning("Fast-path pre-pass failed; falling back to full review review_id=%s err=%s", context.get("review_id"), exc)
        decision = fallback_full_review(f"Fast-path pre-pass failed: {exc}", risk_labels=["fast_path_error"])
        fallback_reason = "fast_path_error"

    metadata = fast_path_metadata(
        decision,
        classified=classified,
        diff_tokens=diff_tokens,
        fallback_reason=fallback_reason,
    )
    context.setdefault("debug_artifacts", {})
    debug_artifacts = context.get("debug_artifacts")
    if isinstance(debug_artifacts, dict):
        debug_artifacts["fast_path_decision"] = metadata
    await _record_model_audit(
        context=context,
        stage="fast_path",
        provider=fast_resolution.provider,
        model=fast_resolution.model,
        token_before=token_snapshot,
        findings_count=0,
        decision=decision.decision,
        model_resolution=fast_resolution,
        extra_metadata=metadata,
    )
    return decision, fast_resolution


def _review_config_for_fast_path_decision(review_config: ReviewConfig, decision: FastPathDecision) -> ReviewConfig:
    if decision.decision != "light_review" or review_config.model.explicit:
        return review_config
    existing = review_config.models.roles.get("primary_review")
    if existing is not None and existing.provider and existing.model:
        return review_config
    roles = dict(review_config.models.roles)
    roles["primary_review"] = replace(existing, tier="economy") if existing is not None else ModelRoleRoutingConfig(tier="economy")
    return replace(review_config, models=replace(review_config.models, roles=roles))


async def run_review(
    review_id: int,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
) -> None:
    await _mark_review_running(review_id, installation_id)

    context: dict[str, Any] = {
        "run_id": str(uuid4()),
        "review_id": review_id,
        "installation_id": installation_id,
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "input_tokens": 0,
        "output_tokens": 0,
        "tokens_used": 0,
    }
    started_at = monotonic()

    try:
        gh, diff_text, pr, commits, review_config = await _fetch_pr_inputs(context)
        context["chunking_config_hash"] = _chunking_config_hash(review_config)

        if pr.get("draft", False) and not review_config.review_drafts:
            result = ReviewResult(findings=[], summary="Skipped automated review because this pull request is a draft.")
            await _mark_review_done(session_data=result, context=context, status="done", review_config=review_config)
            return
        diff_tokens = count_tokens(diff_text)
        chunking_enabled = review_config.chunking.enabled and diff_tokens >= review_config.chunking.proactive_threshold_tokens
        if is_diff_too_large(diff_text) and not chunking_enabled:
            result = ReviewResult(
                findings=[],
                summary="PR is too large for automated review. Please split it into smaller changes and re-run.",
            )
            await post_review(gh, owner, repo, pr_number, head_sha, result)
            await _mark_review_done(session_data=result, context=context, status="done", review_config=review_config)
            return
        fast_path_decision, fast_path_resolution = await _run_fast_path_stage(
            context=context,
            diff_text=diff_text,
            pr=pr,
            commits=commits,
            review_config=review_config,
            diff_tokens=diff_tokens,
        )
        if fast_path_decision.decision == "skip_review":
            if fast_path_resolution is not None:
                _set_runtime_model_context(context, fast_path_resolution)
            result = ReviewResult(
                findings=[],
                summary="Skipped full review after low-risk fast-path classification.",
            )
            await _mark_review_done(session_data=result, context=context, status="done", review_config=review_config)
            return
        effective_review_config = _review_config_for_fast_path_decision(review_config, fast_path_decision)
        if chunking_enabled:
            final_result = await _run_chunked_review(
                gh=gh,
                context=context,
                diff_text=diff_text,
                pr=pr,
                commits=commits,
                review_config=effective_review_config,
                started_at=started_at,
            )
            prior_reviews = await gh.get_pr_reviews_by_bot(owner, repo, pr_number)
            editor_resolution = _resolve_runtime_model(
                context,
                effective_review_config,
                "editor",
                previous_provider=str(context.get("runtime_model_provider", "")) or None,
            )
            edited_result = await run_editor(
                draft=final_result,
                pr_context={
                    "title": pr.get("title", ""),
                    "description": pr.get("body", "") or "",
                    "commits": [str((commit.get("commit") or {}).get("message", "")) for commit in commits],
                },
                prior_reviews=prior_reviews,
                code_acknowledgments=[],
                model_name=editor_resolution.model,
                provider=editor_resolution.provider,
                context=context,
            )
            final_result = ReviewResult(findings=edited_result.findings, summary=edited_result.summary)
            final_result = _apply_review_config_filters(final_result, effective_review_config)
            review_post_response = await post_review(gh, owner, repo, pr_number, head_sha, final_result)
            comment_ids = extract_review_comment_ids(review_post_response)
            await seed_pending_finding_outcomes(
                review_id=cast(int, context["review_id"]),
                installation_id=cast(int, context["installation_id"]),
                finding_count=len(final_result.findings),
                github_comment_ids=comment_ids,
            )
            await _mark_review_done(session_data=final_result, context=context, status="done", review_config=effective_review_config)
            logger.info(
                "Chunked review completed review_id=%s duration_ms=%s",
                review_id,
                int((monotonic() - started_at) * 1000),
            )
            return

        review_config = effective_review_config
        files_in_diff, fetched_map, context_bundle, system_prompt, user_prompt = await _assemble_context(
            gh, context, diff_text, review_config
        )
        primary_resolution = _resolve_runtime_model(
            context,
            review_config,
            "primary_review",
            context_tokens=count_tokens(system_prompt) + count_tokens(user_prompt),
        )
        token_snapshot = _token_snapshot(context)
        messages = await run_agent(
            system_prompt,
            user_prompt,
            context,
            model_name=primary_resolution.model,
            provider=primary_resolution.provider,
        )
        result = await finalize_review(
            system_prompt,
            messages,
            context,
            model_name=primary_resolution.model,
            provider=primary_resolution.provider,
        )
        await _record_model_audit(
            context=context,
            stage="primary",
            provider=primary_resolution.provider,
            model=primary_resolution.model,
            token_before=token_snapshot,
            findings_count=len(result.findings),
            decision="generated",
            model_resolution=primary_resolution,
        )
        tools_called_per_file = extract_tool_usage_by_file(messages)
        tool_call_history = extract_tool_call_history(messages)
        for finding in result.findings:
            finding.verified_via_tool = finding.file_path in tools_called_per_file

        commentable_lines = right_side_diff_line_set(files_in_diff)
        validator = FindingValidator(
            fetched_map,
            commentable_lines=commentable_lines,
        )
        result.findings = _repair_findings_from_files(
            result.findings,
            fetched_map,
            commentable_lines=commentable_lines,
            window=REPAIR_SEARCH_WINDOW,
        )
        result, validator_dropped, generated = _validate_result(result, validator)
        retry_triggered = False
        retry_mode: str | None = None
        retry_recovered: int = 0
        retry_attempted: int = 0
        mismatch_subtypes = _summarize_target_line_mismatch_subtypes(
            validator_dropped,
            fetched_map,
            commentable_lines=commentable_lines,
            window=REPAIR_SEARCH_WINDOW,
        )

        dropped_count = len(validator_dropped)
        drop_rate = dropped_count / generated if generated else 0.0
        mismatch_dropped = [entry for entry in validator_dropped if entry[1] == "target_line_mismatch"]
        if generated > 0 and drop_rate >= REPAIR_RETRY_DROP_RATE:
            if mismatch_dropped:
                retry_triggered = True
                retry_mode = "repair_only"
                retry_attempted = len(mismatch_dropped)
                repair_prompt = _repair_retry_feedback(
                    mismatch_dropped,
                    fetched_map,
                    window=REPAIR_SEARCH_WINDOW,
                )
                logger.warning(
                    "Retrying with focused repair pass review_id=%s dropped=%s generated=%s",
                    review_id,
                    dropped_count,
                    generated,
                )
                repaired = await finalize_review(
                    system_prompt,
                    [{"role": "user", "content": repair_prompt}],
                    context,
                    model_name=primary_resolution.model,
                    provider=primary_resolution.provider,
                    allow_retry=False,
                )
                repaired.findings = _repair_findings_from_files(
                    repaired.findings,
                    fetched_map,
                    commentable_lines=commentable_lines,
                    window=REPAIR_SEARCH_WINDOW,
                )
                repaired_validated, repaired_dropped, _ = _validate_result(repaired, validator)
                retry_recovered = len(repaired_validated.findings)
                recovery_ratio = retry_recovered / retry_attempted if retry_attempted else 0.0
                if recovery_ratio >= MIN_RECOVERY_RATIO_FOR_SUCCESS:
                    result.findings.extend(repaired_validated.findings)
                validator_dropped.extend(repaired_dropped)
                mismatch_subtypes = _summarize_target_line_mismatch_subtypes(
                    validator_dropped,
                    fetched_map,
                    commentable_lines=commentable_lines,
                    window=REPAIR_SEARCH_WINDOW,
                )
            elif drop_rate >= FULL_REGENERATE_RETRY_DROP_RATE:
                retry_triggered = True
                retry_mode = "full_regenerate"
                retry_attempted = dropped_count
                feedback = _validation_feedback(validator_dropped)
                logger.warning(
                    "Retrying review generation due to high invalid finding rate review_id=%s",
                    review_id,
                )
                retried = await finalize_review(
                    system_prompt,
                    messages,
                    context,
                    validation_feedback=feedback,
                    model_name=primary_resolution.model,
                    provider=primary_resolution.provider,
                )
                retried.findings = _repair_findings_from_files(
                    retried.findings,
                    fetched_map,
                    commentable_lines=commentable_lines,
                    window=REPAIR_SEARCH_WINDOW,
                )
                result, validator_dropped, generated = _validate_result(retried, validator)
                retry_recovered = len(result.findings)
                mismatch_subtypes = _summarize_target_line_mismatch_subtypes(
                    validator_dropped,
                    fetched_map,
                    commentable_lines=commentable_lines,
                    window=REPAIR_SEARCH_WINDOW,
                )

        threshold = review_config.confidence_threshold or 85
        result, confidence_dropped, evidence_rejections, evidence_rejection_reasons = _apply_policy_filters(
            result,
            threshold=threshold,
            tool_call_history=tool_call_history,
            known_fact_ids=load_verified_fact_ids(),
        )
        draft_result = ReviewResult(findings=list(result.findings), summary=result.summary)
        debate_conflict_score: int | None = None
        if review_config.max_mode.enabled and fast_path_decision.decision != "light_review":
            challenger_resolution = _resolve_runtime_model(
                context,
                review_config,
                "challenger",
                context_tokens=count_tokens(system_prompt) + count_tokens(_build_challenger_prompt(draft_result, final_summary_hint=result.summary)),
                previous_provider=primary_resolution.provider,
            )
            challenger_prompt = _build_challenger_prompt(draft_result, final_summary_hint=result.summary)
            challenger_messages = [{"role": "user", "content": challenger_prompt}]
            challenger_snapshot = _token_snapshot(context)
            challenger_result = await finalize_review(
                system_prompt,
                challenger_messages,
                context,
                model_name=challenger_resolution.model,
                provider=challenger_resolution.provider,
                allow_retry=False,
            )
            debate_conflict_score = _calculate_conflict_score(draft_result.findings, challenger_result.findings)
            await _record_model_audit(
                context=context,
                stage="challenger",
                provider=challenger_resolution.provider,
                model=challenger_resolution.model,
                token_before=challenger_snapshot,
                findings_count=len(challenger_result.findings),
                conflict_score=debate_conflict_score,
                decision="challenged",
                model_resolution=challenger_resolution,
            )
            tie_break_result: ReviewResult | None = None
            should_tie_break = debate_conflict_score >= review_config.max_mode.conflict_threshold or _has_high_risk_findings(
                draft_result.findings, review_config.max_mode.high_risk_severity
            )
            if should_tie_break:
                tie_break_resolution = _resolve_runtime_model(
                    context,
                    review_config,
                    "tie_break",
                    context_tokens=count_tokens(system_prompt) + count_tokens(_build_tie_break_prompt(draft_result, challenger_result)),
                    previous_provider=challenger_resolution.provider,
                )
                tie_break_prompt = _build_tie_break_prompt(draft_result, challenger_result)
                tie_break_snapshot = _token_snapshot(context)
                tie_break_result = await finalize_review(
                    system_prompt,
                    [{"role": "user", "content": tie_break_prompt}],
                    context,
                    model_name=tie_break_resolution.model,
                    provider=tie_break_resolution.provider,
                    allow_retry=False,
                )
                await _record_model_audit(
                    context=context,
                    stage="tie_break",
                    provider=tie_break_resolution.provider,
                    model=tie_break_resolution.model,
                    token_before=tie_break_snapshot,
                    findings_count=len(tie_break_result.findings),
                    conflict_score=debate_conflict_score,
                    decision="tie_break",
                    model_resolution=tie_break_resolution,
                )
            draft_result = _merge_debate_results(
                primary=draft_result,
                challenger=challenger_result,
                tie_break=tie_break_result,
            )
        code_acknowledgments = extract_todo_fixme_markers(fetched_map)
        prior_reviews = await gh.get_pr_reviews_by_bot(owner, repo, pr_number)
        editor_resolution = _resolve_runtime_model(
            context,
            review_config,
            "editor",
            previous_provider=primary_resolution.provider,
        )
        editor_snapshot = _token_snapshot(context)
        edited_result = await run_editor(
            draft=draft_result,
            pr_context={
                "title": pr.get("title", ""),
                "description": pr.get("body", "") or "",
                "commits": [str((commit.get("commit") or {}).get("message", "")) for commit in commits],
            },
            prior_reviews=prior_reviews,
            code_acknowledgments=code_acknowledgments,
            model_name=editor_resolution.model,
            provider=editor_resolution.provider,
            context=context,
        )
        await _record_model_audit(
            context=context,
            stage="editor",
            provider=editor_resolution.provider,
            model=editor_resolution.model,
            token_before=editor_snapshot,
            findings_count=len(draft_result.findings),
            accepted_findings_count=len(edited_result.findings),
            decision="edited",
            model_resolution=editor_resolution,
        )
        final_result = ReviewResult(findings=edited_result.findings, summary=edited_result.summary)
        final_result = _apply_review_config_filters(final_result, review_config)
        await _record_model_audit(
            context=context,
            stage="final_post",
            provider=primary_resolution.provider,
            model=primary_resolution.model,
            token_before=_token_snapshot(context),
            findings_count=len(draft_result.findings),
            accepted_findings_count=len(final_result.findings),
            conflict_score=debate_conflict_score,
            decision="posted",
            model_resolution=primary_resolution,
        )
        _attach_debug_artifacts(
            context=context,
            generated=generated,
            validator_dropped=validator_dropped,
            confidence_dropped=confidence_dropped,
            draft_findings=len(draft_result.findings),
            final_findings=len(final_result.findings),
            editor_actions=Counter(decision.action for decision in edited_result.decisions),
            editor_drop_reasons=Counter(
                decision.reason for decision in edited_result.decisions if decision.action == "drop" and decision.reason
            ),
            severity_draft=Counter(finding.severity for finding in draft_result.findings),
            severity_final=Counter(finding.severity for finding in final_result.findings),
            confidence_draft=Counter(_confidence_bucket(finding.confidence) for finding in draft_result.findings),
            confidence_final=Counter(_confidence_bucket(finding.confidence) for finding in final_result.findings),
            evidence_distribution=Counter(finding.evidence for finding in final_result.findings),
            evidence_rejections_total=len(evidence_rejections),
            evidence_rejection_reasons=evidence_rejection_reasons,
            retry_triggered=retry_triggered,
            retry_mode=retry_mode,
            retry_attempted=retry_attempted,
            retry_recovered=retry_recovered,
            threshold=threshold,
            context_telemetry=context_bundle.telemetry,
            mismatch_subtypes=mismatch_subtypes,
            debate_conflict_score=debate_conflict_score,
        )
        _log_quality_metrics(
            context=context,
            frameworks=context.get("frameworks", []),
            review_config=review_config,
            generated=generated,
            validator_dropped=validator_dropped,
            confidence_dropped=confidence_dropped,
            draft_posted=len(draft_result.findings),
            final_posted=len(final_result.findings),
            editor_result=edited_result,
            evidence_distribution=Counter(finding.evidence for finding in final_result.findings),
            evidence_rejections_total=len(evidence_rejections),
            evidence_rejection_reasons=evidence_rejection_reasons,
            context_telemetry=context_bundle.telemetry,
        )

        review_post_response = await post_review(gh, owner, repo, pr_number, head_sha, final_result)
        comment_ids = extract_review_comment_ids(review_post_response)
        await seed_pending_finding_outcomes(
            review_id=cast(int, context["review_id"]),
            installation_id=cast(int, context["installation_id"]),
            finding_count=len(final_result.findings),
            github_comment_ids=comment_ids,
        )
        await _mark_review_done(session_data=final_result, context=context, status="done", review_config=review_config)
        logger.info(
            "Review completed review_id=%s duration_ms=%s first_model_call_latency_ms=%s",
            review_id,
            int((monotonic() - started_at) * 1000),
            context.get("first_model_call_latency_ms", 0),
        )
    except Exception as exc:
        logger.exception("Review job failed review_id=%s", review_id)
        await _mark_review_done(
            session_data=ReviewResult(findings=[], summary=f"Review failed: {exc}"),
            context=context,
            status="failed",
            review_config=review_config if "review_config" in locals() else None,
        )
        logger.info("Review failed review_id=%s duration_ms=%s", review_id, int((monotonic() - started_at) * 1000))
        raise


async def _mark_review_done(
    session_data: ReviewResult,
    context: dict[str, Any],
    status: str,
    review_config: ReviewConfig | None = None,
) -> None:
    input_price = _decimal_from_context(context.get("runtime_input_per_1m_usd")) or (
        review_config.model.input_per_1m_usd if review_config else Decimal("3.00")
    )
    cached_input_price = _decimal_from_context(context.get("runtime_cached_input_per_1m_usd")) or (
        review_config.model.cached_input_per_1m_usd if review_config else None
    )
    output_price = _decimal_from_context(context.get("runtime_output_per_1m_usd")) or (
        review_config.model.output_per_1m_usd if review_config else Decimal("15.00")
    )
    cost = _estimate_cost_usd(
        context.get("input_tokens", 0),
        context.get("output_tokens", 0),
        input_per_1m_usd=input_price,
        output_per_1m_usd=output_price,
        cached_input_tokens=_cached_input_tokens(context),
        cached_input_per_1m_usd=cached_input_price,
    )
    installation_id = cast(int, context["installation_id"])
    await _record_token_budget_usage(installation_id, int(context.get("tokens_used", 0)))
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, cast(int, context["review_id"]))
        if review is None:
            return
        review.status = status
        if review_config is not None:
            review.model_provider = str(context.get("runtime_model_provider") or review_config.model.provider)
            review.model = str(context.get("runtime_model") or review_config.model.name)
        review.findings = session_data.model_dump(mode="json")
        current_artifacts = dict(review.debug_artifacts or {})
        incoming_artifacts = context.get("debug_artifacts")
        if isinstance(incoming_artifacts, dict):
            current_artifacts.update(incoming_artifacts)
        review.debug_artifacts = current_artifacts or None
        review.tokens_used = int(context.get("tokens_used", 0))
        review.cost_usd = float(cost)
        review.completed_at = datetime.now(timezone.utc)
        await session.commit()


def _estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    *,
    input_per_1m_usd: Decimal,
    output_per_1m_usd: Decimal,
    cached_input_tokens: int = 0,
    cached_input_per_1m_usd: Decimal | None = None,
) -> Decimal:
    cached_tokens = min(max(cached_input_tokens, 0), max(input_tokens, 0))
    uncached_tokens = max(input_tokens - cached_tokens, 0)
    input_cost = Decimal(uncached_tokens) / Decimal(1_000_000) * input_per_1m_usd
    if cached_tokens and cached_input_per_1m_usd is not None:
        input_cost += Decimal(cached_tokens) / Decimal(1_000_000) * cached_input_per_1m_usd
    else:
        input_cost += Decimal(cached_tokens) / Decimal(1_000_000) * input_per_1m_usd
    output_cost = Decimal(output_tokens) / Decimal(1_000_000) * output_per_1m_usd
    return (input_cost + output_cost).quantize(Decimal("0.000001"))


def _cached_input_tokens(context: dict[str, Any]) -> int:
    entries = context.get("llm_usage", [])
    if not isinstance(entries, list):
        return 0
    return sum(int(entry.get("cached_input_tokens", 0) or 0) for entry in entries if isinstance(entry, dict))


def _decimal_from_context(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


async def _record_token_budget_usage(installation_id: int, tokens_used: int) -> None:
    if tokens_used <= 0:
        return
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        allowed = await check_and_consume_daily_token_budget(
            redis,
            installation_id,
            tokens=tokens_used,
            daily_limit=settings.daily_token_budget_per_installation,
        )
        current = await current_daily_token_usage(redis, installation_id)
        if current >= int(settings.daily_token_budget_per_installation * 0.8):
            logger.warning(
                "Installation nearing daily token budget installation_id=%s used=%s limit=%s",
                installation_id,
                current,
                settings.daily_token_budget_per_installation,
            )
        if not allowed:
            logger.warning(
                "Installation exceeded daily token budget installation_id=%s used=%s limit=%s",
                installation_id,
                current,
                settings.daily_token_budget_per_installation,
            )
    except redis_exc.RedisError as exc:
        logger.warning(
            "Skipping token budget recording (Redis unavailable) installation_id=%s tokens=%s err=%s",
            installation_id,
            tokens_used,
            exc,
        )
    finally:
        try:
            await redis.aclose()
        except redis_exc.RedisError:
            pass
        except OSError:
            pass


async def _load_review_config_cached(gh: GitHubClient, owner: str, repo: str, head_sha: str) -> ReviewConfig:
    cached = await get_cached_review_config(owner, repo, head_sha)
    if cached is not None:
        return cached
    loaded = await load_review_config(gh, owner, repo, head_sha)
    await set_cached_review_config(owner, repo, head_sha, loaded)
    return loaded


def _chunking_config_hash(review_config: ReviewConfig) -> str:
    payload = {
        "chunking": {
            "enabled": review_config.chunking.enabled,
            "proactive_threshold_tokens": review_config.chunking.proactive_threshold_tokens,
            "target_chunk_tokens": review_config.chunking.target_chunk_tokens,
            "max_chunks": review_config.chunking.max_chunks,
            "min_files_per_chunk": review_config.chunking.min_files_per_chunk,
            "include_file_classes": review_config.chunking.include_file_classes,
            "max_total_prompt_tokens": review_config.chunking.max_total_prompt_tokens,
            "max_latency_seconds": review_config.chunking.max_latency_seconds,
            "output_headroom_tokens": review_config.chunking.output_headroom_tokens,
        }
    }
    serialized = json.dumps(payload, sort_keys=True)
    return sha256(serialized.encode("utf-8")).hexdigest()


async def _run_chunked_review(
    *,
    gh: GitHubClient,
    context: dict[str, Any],
    diff_text: str,
    pr: dict[str, Any],
    commits: list[dict[str, Any]],
    review_config: ReviewConfig,
    started_at: float,
) -> ReviewResult:
    owner = cast(str, context["owner"])
    repo = cast(str, context["repo"])
    pr_number = cast(int, context["pr_number"])
    head_sha = cast(str, context["head_sha"])
    files_in_diff = _filter_diff_files(parse_diff(diff_text), review_config.ignore_paths)
    include_file_classes = tuple(
        file_class
        for file_class in review_config.chunking.include_file_classes
        if file_class in ALLOWED_CHUNK_FILE_CLASSES
    )
    if not include_file_classes:
        include_file_classes = ("reviewable", "config_only", "test_only")
    planner_config = ChunkingPlannerConfig(
        enabled=review_config.chunking.enabled,
        proactive_threshold_tokens=review_config.chunking.proactive_threshold_tokens,
        target_chunk_tokens=review_config.chunking.target_chunk_tokens,
        max_chunks=review_config.chunking.max_chunks,
        min_files_per_chunk=review_config.chunking.min_files_per_chunk,
        include_file_classes=include_file_classes,
        max_total_prompt_tokens=review_config.chunking.max_total_prompt_tokens,
        max_latency_seconds=review_config.chunking.max_latency_seconds,
        output_headroom_tokens=review_config.chunking.output_headroom_tokens,
    )
    chunk_plan = plan_chunks(
        files_in_diff,
        planner_config,
        pr_title=str(pr.get("title", "")),
        pr_body=str(pr.get("body", "") or ""),
        generated_paths=review_config.packaging.generated_paths,
        vendor_paths=review_config.packaging.vendor_paths,
    )
    if not chunk_plan.chunks:
        return ReviewResult(findings=[], summary=f"{chunk_plan.coverage_note} No findings generated.")

    repo_profile = await profile_repo(gh, owner, repo, head_sha)
    base_repo_segments = _build_repo_segments(repo_profile.frameworks, review_config.prompt_additions)
    resume_state = await load_chunk_state(context)
    chunk_state = merge_chunk_state_with_plan(resume_state, chunk_plan)
    structured_findings: list[Finding] = []
    chunk_summaries: list[str] = []
    elapsed_budget_exhausted = False
    prompt_budget_exhausted = False

    for chunk in chunk_plan.chunks:
        now_elapsed = int(monotonic() - started_at)
        if now_elapsed >= review_config.chunking.max_latency_seconds:
            elapsed_budget_exhausted = True
            break
        if chunk_status(chunk_state, chunk.chunk_id) == "done":
            structured_findings.extend(_chunk_findings_from_state(chunk_state, chunk.chunk_id))
            chunk_summaries.append(_chunk_summary_from_state(chunk_state, chunk.chunk_id))
            continue

        chunk_files = [entry.file_in_diff for entry in chunk.files]
        chunk_repo_context = chunk_repo_segments(chunk_plan, chunk)
        context_bundle = await build_context_bundle(
            gh,
            owner,
            repo,
            head_sha,
            chunk_files,
            budgets=review_config.budgets,
            packaging=review_config.packaging,
            repo_segments=[*base_repo_segments, *chunk_repo_context],
        )
        chunk_diff = render_chunk_diff(chunk_files)
        system_prompt = build_system_prompt(repo_profile.frameworks, chunk_diff, review_config.prompt_additions)
        user_prompt = build_initial_user_prompt(
            owner,
            repo,
            pr_number,
            f"{context_bundle.rendered}\n\nChunk coverage note: {chunk_plan.coverage_note}",
        )
        chunk_resolution = _resolve_runtime_model(
            context,
            review_config,
            "chunk_review",
            context_tokens=count_tokens(system_prompt) + count_tokens(user_prompt),
        )
        projected_prompt_cost = count_tokens(system_prompt) + count_tokens(user_prompt) + review_config.chunking.output_headroom_tokens
        if (int(context.get("tokens_used", 0)) + projected_prompt_cost) > review_config.chunking.max_total_prompt_tokens:
            prompt_budget_exhausted = True
            break

        _set_chunk_state(chunk_state, chunk.chunk_id, status="running")
        await persist_chunk_state(context, chunk_state)
        try:
            messages = await run_agent(
                system_prompt,
                user_prompt,
                context,
                model_name=chunk_resolution.model,
                provider=chunk_resolution.provider,
            )
            chunk_result = await finalize_review(
                system_prompt,
                messages,
                context,
                model_name=chunk_resolution.model,
                provider=chunk_resolution.provider,
            )
            chunk_result.findings = _repair_findings_from_files(
                chunk_result.findings,
                dict(context_bundle.fetched_files),
                commentable_lines=right_side_diff_line_set(chunk_files),
                window=REPAIR_SEARCH_WINDOW,
            )
            chunk_result.findings = attach_anchor_metadata(chunk_result.findings, chunk_files)
            valid_findings = filter_findings_with_valid_anchors(chunk_result.findings, chunk_files)
            postprocessed_chunk, _, _, _ = _apply_policy_filters(
                ReviewResult(findings=valid_findings, summary=chunk_result.summary),
                threshold=review_config.confidence_threshold or 85,
                tool_call_history=extract_tool_call_history(messages),
                known_fact_ids=load_verified_fact_ids(),
            )
            structured_findings.extend(postprocessed_chunk.findings)
            chunk_summaries.append(chunk_result.summary)
            _set_chunk_state(
                chunk_state,
                chunk.chunk_id,
                status="done",
                findings=[item.model_dump(mode="json") for item in postprocessed_chunk.findings],
                summary=chunk_result.summary,
                estimated_prompt_tokens=chunk.estimated_prompt_tokens,
            )
        except Exception as exc:
            _set_chunk_state(chunk_state, chunk.chunk_id, status="failed", error=str(exc))
            await persist_chunk_state(context, chunk_state)
            raise
        await persist_chunk_state(context, chunk_state)

    synthesis_result = await _run_cross_chunk_synthesis(
        chunk_plan=chunk_plan,
        chunk_summaries=chunk_summaries,
        structured_findings=structured_findings,
        context=context,
        review_config=review_config,
        frameworks=repo_profile.frameworks,
    )
    synthesis_findings = filter_findings_with_valid_anchors(
        attach_anchor_metadata(synthesis_result.findings, files_in_diff),
        files_in_diff,
    )
    synthesis_processed, _, _, _ = _apply_policy_filters(
        ReviewResult(findings=synthesis_findings, summary=synthesis_result.summary),
        threshold=review_config.confidence_threshold or 85,
        tool_call_history=[],
        known_fact_ids=load_verified_fact_ids(),
    )
    merged = dedupe_findings([*structured_findings, *synthesis_processed.findings])
    final_summary_parts = [chunk_plan.coverage_note, synthesis_result.summary.strip()]
    if chunk_plan.is_partial:
        final_summary_parts.append("Partial coverage: max chunk count reached.")
    if prompt_budget_exhausted:
        final_summary_parts.append("Partial coverage: stopped at total prompt budget limit.")
    if elapsed_budget_exhausted:
        final_summary_parts.append("Partial coverage: stopped at latency limit.")
    context["debug_artifacts"] = {
        "chunking_state": chunk_state,
        "chunking_plan": {
            "chunks": [chunk.chunk_id for chunk in chunk_plan.chunks],
            "skipped_files": [item.path for item in chunk_plan.skipped_files],
            "is_partial": chunk_plan.is_partial,
            "coverage_note": chunk_plan.coverage_note,
        },
        "llm_model_resolutions": context.get("llm_model_resolutions", {}),
        "llm_usage": context.get("llm_usage", []),
    }
    return ReviewResult(
        findings=merged,
        summary=(" ".join(part for part in final_summary_parts if part))[:780],
    )


def _chunk_repo_segments(chunk_plan: ChunkPlan, chunk: PlannedChunk) -> list[str]:
    files = [entry.path for entry in chunk.files]
    chunk_packages = sorted({entry.touched_package for entry in chunk.files})
    chunk_dep_hints = sorted({hint for entry in chunk.files if (hint := entry.dependency_hint) is not None})
    return [
        "Full changed-file manifest:\n" + "\n".join(chunk_plan.full_manifest),
        "Touched packages: " + (", ".join(chunk_plan.touched_packages) if chunk_plan.touched_packages else "none"),
        "Dependency hints: " + (", ".join(chunk_plan.dependency_hints) if chunk_plan.dependency_hints else "none"),
        f"Active chunk files ({len(files)}):\n" + "\n".join(files),
        "Active chunk package scope: " + (", ".join(chunk_packages) if chunk_packages else "none"),
        "Active chunk dependency hints: " + (", ".join(chunk_dep_hints) if chunk_dep_hints else "none"),
    ]


def _render_chunk_diff(files_in_diff: list[FileInDiff]) -> str:
    rendered: list[str] = []
    for file in files_in_diff:
        rendered.append(f"diff -- {file.path}")
        for line in file.numbered_lines:
            marker = {"add": "+", "del": "-", "ctx": " "}[line.kind]
            rendered.append(f"{marker}{line.content}")
    return "\n".join(rendered)


async def _run_cross_chunk_synthesis(
    *,
    chunk_plan: ChunkPlan,
    chunk_summaries: list[str],
    structured_findings: list[Finding],
    context: dict[str, Any],
    review_config: ReviewConfig,
    frameworks: list[str],
) -> ReviewResult:
    if not chunk_summaries:
        return ReviewResult(findings=[], summary="No chunk summaries were available for synthesis.")
    synthesis_prompt = "\n".join(
        [
            "You are running an integration synthesis pass across chunk-level review outputs.",
            "Find only issues that span chunk boundaries or depend on interactions between files/chunks.",
            "Do not repeat chunk-local findings unless integration risk changes severity.",
            "Changed file manifest:",
            *chunk_plan.full_manifest,
            "Chunk summaries:",
            *[f"- {item}" for item in chunk_summaries],
            f"Chunk finding count: {len(structured_findings)}",
        ]
    )
    system_prompt = build_system_prompt(frameworks, "", review_config.prompt_additions)
    synthesis_resolution = _resolve_runtime_model(
        context,
        review_config,
        "synthesis",
        context_tokens=count_tokens(system_prompt) + count_tokens(synthesis_prompt),
    )
    return await finalize_review(
        system_prompt,
        [{"role": "user", "content": synthesis_prompt}],
        context,
        model_name=synthesis_resolution.model,
        provider=synthesis_resolution.provider,
        allow_retry=False,
    )


def _finding_dedupe_key(finding: Finding) -> tuple[str, int, str, str, str]:
    line_value = finding.line_end or finding.line_start
    side = finding.side
    normalized_title = normalize_for_match(finding.message[:120])
    normalized_excerpt = normalize_for_match(finding.target_line_content[:240])
    return (finding.file_path, line_value, side, normalized_title, f"{finding.category}:{normalized_excerpt}")


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    merged: dict[tuple[str, int, str, str, str], Finding] = {}
    for finding in findings:
        key = _finding_dedupe_key(finding)
        existing = merged.get(key)
        if existing is None:
            merged[key] = finding
            continue
        if SEVERITY_RANK[finding.severity] > SEVERITY_RANK[existing.severity]:
            merged[key] = finding
            continue
        if finding.confidence > existing.confidence:
            merged[key] = finding
    return sorted(
        merged.values(),
        key=lambda item: (SEVERITY_RANK[item.severity], item.confidence),
        reverse=True,
    )


def _attach_anchor_metadata(findings: list[Finding], files_in_diff: list[FileInDiff]) -> list[Finding]:
    index = _build_diff_anchor_index(files_in_diff)
    updated: list[Finding] = []
    for finding in findings:
        anchor = index.get((finding.file_path, finding.line_start))
        if anchor is None:
            updated.append(finding)
            continue
        new_line_no = anchor["new_line_no"]
        old_line_no = anchor["old_line_no"]
        hunk_id = anchor["hunk_id"]
        finding.side = "RIGHT" if new_line_no is not None else "LEFT"
        finding.start_side = finding.side
        finding.old_line_no = old_line_no
        finding.new_line_no = new_line_no
        finding.patch_hunk = hunk_id
        updated.append(finding)
    return updated


def _build_diff_anchor_index(files_in_diff: list[FileInDiff]) -> dict[tuple[str, int], DiffAnchorMetadata]:
    index: dict[tuple[str, int], DiffAnchorMetadata] = {}
    for file in files_in_diff:
        hunk_id = 0
        previous_line = -1
        for numbered in file.numbered_lines:
            anchor = numbered.new_line_no if numbered.new_line_no is not None else numbered.old_line_no
            if anchor is None:
                continue
            if previous_line != -1 and anchor > previous_line + 1:
                hunk_id += 1
            key = (file.path, anchor)
            index[key] = {
                "new_line_no": numbered.new_line_no,
                "old_line_no": numbered.old_line_no,
                "hunk_id": f"{file.path}:hunk:{hunk_id}",
            }
            previous_line = anchor
    return index


def _filter_findings_with_valid_anchors(findings: list[Finding], files_in_diff: list[FileInDiff]) -> list[Finding]:
    allowed = _build_diff_anchor_index(files_in_diff)
    filtered: list[Finding] = []
    for finding in findings:
        anchor_line = finding.line_end or finding.line_start
        if (finding.file_path, anchor_line) not in allowed:
            continue
        filtered.append(finding)
    return filtered


def _chunk_state_key(context: dict[str, Any]) -> str:
    payload = {
        "repo": context["repo"],
        "pr_number": context["pr_number"],
        "head_sha": context["head_sha"],
        "config_hash": context.get("chunking_config_hash", "default"),
    }
    digest = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"chunking:{digest}"


async def _load_chunk_state(context: dict[str, Any]) -> dict[str, dict[str, object]]:
    installation_id = cast(int, context["installation_id"])
    review_id = cast(int, context["review_id"])
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None or not review.debug_artifacts:
            return {}
        chunking_state = review.debug_artifacts.get("chunking_state")
        if not isinstance(chunking_state, dict):
            return {}
        state = chunking_state.get(_chunk_state_key(context))
        if not isinstance(state, dict):
            return {}
        return cast(dict[str, dict[str, object]], state)


def _merge_chunk_state_with_plan(existing: dict[str, dict[str, object]], plan: ChunkPlan) -> dict[str, dict[str, object]]:
    merged = dict(existing)
    for chunk in plan.chunks:
        if chunk.chunk_id not in merged:
            merged[chunk.chunk_id] = {"status": "pending", "findings": [], "summary": ""}
    return merged


def _chunk_status(state: dict[str, dict[str, object]], chunk_id: str) -> str:
    chunk_state = state.get(chunk_id, {})
    status = chunk_state.get("status")
    return str(status) if isinstance(status, str) else "pending"


def _chunk_findings_from_state(state: dict[str, dict[str, object]], chunk_id: str) -> list[Finding]:
    chunk_state = state.get(chunk_id, {})
    findings_raw = chunk_state.get("findings")
    if not isinstance(findings_raw, list):
        return []
    findings: list[Finding] = []
    for entry in findings_raw:
        if not isinstance(entry, dict):
            continue
        try:
            findings.append(Finding.model_validate(entry))
        except ValidationError:
            continue
    return findings


def _chunk_summary_from_state(state: dict[str, dict[str, object]], chunk_id: str) -> str:
    summary = state.get(chunk_id, {}).get("summary")
    return str(summary) if isinstance(summary, str) else ""


def _set_chunk_state(
    state: dict[str, dict[str, object]],
    chunk_id: str,
    *,
    status: str,
    findings: list[dict[str, object]] | None = None,
    summary: str | None = None,
    estimated_prompt_tokens: int | None = None,
    error: str | None = None,
) -> None:
    chunk_state = state.setdefault(chunk_id, {})
    chunk_state["status"] = status
    if findings is not None:
        chunk_state["findings"] = findings
    if summary is not None:
        chunk_state["summary"] = summary
    if estimated_prompt_tokens is not None:
        chunk_state["estimated_prompt_tokens"] = estimated_prompt_tokens
    if error is not None:
        chunk_state["error"] = error


async def _persist_chunk_state(context: dict[str, Any], chunk_state: dict[str, dict[str, object]]) -> None:
    installation_id = cast(int, context["installation_id"])
    review_id = cast(int, context["review_id"])
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            return
        debug_artifacts = dict(review.debug_artifacts or {})
        chunking_state = dict(debug_artifacts.get("chunking_state") or {})
        chunking_state[_chunk_state_key(context)] = chunk_state
        debug_artifacts["chunking_state"] = chunking_state
        review.debug_artifacts = debug_artifacts
        await session.commit()


def _filter_diff_files(files_in_diff: list[FileInDiff], ignore_paths: list[str]) -> list[FileInDiff]:
    if not ignore_paths:
        return files_in_diff
    filtered: list[FileInDiff] = []
    ignored_count = 0
    for file_in_diff in files_in_diff:
        path = str(getattr(file_in_diff, "path", ""))
        if any(fnmatch(path, pattern) for pattern in ignore_paths):
            ignored_count += 1
            continue
        filtered.append(file_in_diff)
    if ignored_count:
        logger.info("Ignored %s diff files based on repo config ignore_paths", ignored_count)
    return filtered


def _apply_review_config_filters(result: ReviewResult, review_config: ReviewConfig) -> ReviewResult:
    allowed_categories = set(review_config.categories)
    filtered: list[Finding] = []
    for finding in result.findings:
        if review_config.ignore_paths and any(fnmatch(finding.file_path, pattern) for pattern in review_config.ignore_paths):
            continue
        if allowed_categories and finding.category not in allowed_categories:
            continue
        if SEVERITY_RANK[finding.severity] < SEVERITY_RANK.get(review_config.severity_threshold, 0):
            continue
        filtered.append(finding)
    if len(filtered) > review_config.max_findings_per_pr:
        filtered = sorted(filtered, key=lambda finding: (SEVERITY_RANK[finding.severity], finding.confidence), reverse=True)[
            : review_config.max_findings_per_pr
        ]
    result.findings = filtered
    return result


def _validate_result(
    result: ReviewResult,
    validator: FindingValidator,
) -> tuple[ReviewResult, list[tuple[Finding, DropReason, str]], int]:
    valid_findings: list[Finding] = []
    dropped: list[tuple[Finding, DropReason, str]] = []
    generated = len(result.findings)
    for finding in result.findings:
        is_valid, reason, detail = validator.validate(finding)
        if is_valid:
            valid_findings.append(finding)
            continue
        dropped_reason = reason or "line_out_of_range"
        dropped_detail = detail or "Unknown validation error"
        dropped.append((finding, dropped_reason, dropped_detail))
        logger.warning("Dropped finding: %s — %s", dropped_reason, dropped_detail)
    result.findings = valid_findings
    return result, dropped, generated


def _apply_confidence_threshold(result: ReviewResult, threshold: int) -> tuple[ReviewResult, list[dict[str, object]]]:
    kept_findings: list[Finding] = []
    dropped: list[dict[str, object]] = []
    for finding in result.findings:
        if finding.confidence >= threshold:
            kept_findings.append(finding)
            continue
        dropped.append(
            {
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end or finding.line_start,
                "confidence": finding.confidence,
                "threshold": threshold,
                "message_excerpt": finding.message[:120],
            }
        )
    result.findings = kept_findings
    return result, dropped


def _apply_policy_filters(
    result: ReviewResult,
    *,
    threshold: int,
    tool_call_history: list[dict[str, object]],
    known_fact_ids: set[str],
) -> tuple[ReviewResult, list[dict[str, object]], list[tuple[Finding, str]], Counter[str]]:
    result, confidence_dropped = _apply_confidence_threshold(result, threshold)
    result.findings, auto_tag_vendor_rejected = auto_tag_vendor_claims(result.findings)
    result.findings, evidence_tool_rejected = cross_check_tool_evidence(result.findings, tool_call_history)
    result.findings, evidence_fact_rejected = cross_check_fact_ids(result.findings, known_fact_ids)
    evidence_rejections = [*auto_tag_vendor_rejected, *evidence_tool_rejected, *evidence_fact_rejected]
    evidence_rejection_reasons = Counter(reason for _, reason in evidence_rejections)
    return result, confidence_dropped, evidence_rejections, evidence_rejection_reasons


def _validation_feedback(dropped: list[tuple[Finding, DropReason, str]]) -> str:
    feedback_lines = ["Previous findings were dropped by validation. Regenerate using exact lines and coherent suggestions."]
    for finding, reason, detail in dropped[:10]:
        feedback_lines.append(
            f"- {finding.file_path}:{finding.line_start}-{finding.line_end or finding.line_start} "
            f"reason={reason} detail={detail} message={finding.message[:120]}"
        )
    return "\n".join(feedback_lines)


def _log_quality_metrics(
    context: dict[str, Any],
    frameworks: list[str],
    review_config: ReviewConfig,
    generated: int,
    validator_dropped: list[tuple[Finding, DropReason, str]],
    confidence_dropped: list[dict[str, object]],
    draft_posted: int,
    final_posted: int,
    editor_result: EditedReview,
    evidence_distribution: Counter[str],
    evidence_rejections_total: int,
    evidence_rejection_reasons: Counter[str],
    context_telemetry: ContextTelemetry,
) -> None:
    dropped_by_reason: dict[str, int] = {}
    for _, reason, _ in validator_dropped:
        dropped_by_reason[reason] = dropped_by_reason.get(reason, 0) + 1
    dropped_by_reason["below_confidence_threshold"] = len(confidence_dropped)
    agent_metrics = context.get("agent_metrics", {})
    editor_actions = Counter(decision.action for decision in editor_result.decisions)
    editor_drop_reasons = Counter(
        decision.reason for decision in editor_result.decisions if decision.action == "drop" and decision.reason
    )

    logger.info(
        "Review quality metrics review_id=%s generated=%s validator_dropped=%s confidence_dropped=%s draft_posted=%s "
        "final_posted=%s threshold=%s frameworks=%s dropped_reasons=%s editor_actions=%s editor_drop_reasons=%s "
        "evidence_distribution=%s evidence_rejections_total=%s evidence_rejection_reasons=%s "
        "context_telemetry=%s agent_metrics=%s prompt_version=%s",
        context.get("review_id"),
        generated,
        len(validator_dropped),
        len(confidence_dropped),
        draft_posted,
        final_posted,
        review_config.confidence_threshold,
        ",".join(frameworks),
        dropped_by_reason,
        dict(editor_actions),
        dict(editor_drop_reasons),
        dict(evidence_distribution),
        evidence_rejections_total,
        dict(evidence_rejection_reasons),
        context_telemetry,
        agent_metrics,
        PROMPT_VERSION,
    )


def _attach_debug_artifacts(
    context: dict[str, Any],
    generated: int,
    validator_dropped: list[tuple[Finding, DropReason, str]],
    confidence_dropped: list[dict[str, object]],
    draft_findings: int,
    final_findings: int,
    editor_actions: Counter[str],
    editor_drop_reasons: Counter[str],
    severity_draft: Counter[str],
    severity_final: Counter[str],
    confidence_draft: Counter[str],
    confidence_final: Counter[str],
    evidence_distribution: Counter[str],
    evidence_rejections_total: int,
    evidence_rejection_reasons: Counter[str],
    retry_triggered: bool,
    retry_mode: str | None,
    retry_attempted: int,
    retry_recovered: int,
    threshold: int,
    context_telemetry: ContextTelemetry,
    mismatch_subtypes: dict[str, int],
    debate_conflict_score: int | None,
) -> None:
    validator_entries = [
        {
            "file_path": finding.file_path,
            "line_start": finding.line_start,
            "line_end": finding.line_end or finding.line_start,
            "reason": reason,
            "detail": detail,
            "message_excerpt": finding.message[:120],
        }
        for finding, reason, detail in validator_dropped
    ]
    existing_debug_artifacts = context.get("debug_artifacts")
    context["debug_artifacts"] = {
        **(existing_debug_artifacts if isinstance(existing_debug_artifacts, dict) else {}),
        "generated_findings_count": generated,
        "validator_dropped": validator_entries,
        "confidence_dropped": confidence_dropped,
        "draft_findings_total": draft_findings,
        "final_findings_total": final_findings,
        "editor_actions": dict(editor_actions),
        "editor_drop_reasons": dict(editor_drop_reasons),
        "severity_draft": dict(severity_draft),
        "severity_final": dict(severity_final),
        "confidence_draft": dict(confidence_draft),
        "confidence_final": dict(confidence_final),
        "evidence_distribution": dict(evidence_distribution),
        "evidence_rejections_total": evidence_rejections_total,
        "evidence_rejection_reasons": dict(evidence_rejection_reasons),
        "retry_triggered": retry_triggered,
        "retry_mode": retry_mode,
        "retry_attempted": retry_attempted,
        "retry_recovered": retry_recovered,
        "retry_reason": "validator_drop_rate_above_20_percent" if retry_triggered else None,
        "acceptance_quality_check": {
            "target_sample_size": 50,
            "manual_review_required": retry_recovered > 0,
            "manual_review_hint": "Review a sample of repaired findings to confirm precision remains high.",
        },
        "confidence_threshold": threshold,
        "target_line_mismatch_subtypes": mismatch_subtypes,
        "context_telemetry": context_telemetry.as_dict(),
        "agent_metrics": context.get("agent_metrics", {}),
        "llm_model_resolutions": context.get("llm_model_resolutions", {}),
        "llm_usage": context.get("llm_usage", []),
        "prompt_version": PROMPT_VERSION,
        "debate_conflict_score": debate_conflict_score,
    }


def _token_snapshot(context: dict[str, Any]) -> dict[str, int]:
    return {
        "input_tokens": int(context.get("input_tokens", 0)),
        "output_tokens": int(context.get("output_tokens", 0)),
        "tokens_used": int(context.get("tokens_used", 0)),
    }


def _llm_usage_since(context: dict[str, Any], token_before: dict[str, int]) -> dict[str, object]:
    entries = context.get("llm_usage", [])
    cached_input_tokens = 0
    cache_creation_input_tokens = 0
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cached_input_tokens += int(entry.get("cached_input_tokens", 0) or 0)
            cache_creation_input_tokens += int(entry.get("cache_creation_input_tokens", 0) or 0)
    return {
        "input_delta": max(0, int(context.get("input_tokens", 0)) - token_before["input_tokens"]),
        "output_delta": max(0, int(context.get("output_tokens", 0)) - token_before["output_tokens"]),
        "total_delta": max(0, int(context.get("tokens_used", 0)) - token_before["tokens_used"]),
        "cached_input_tokens_seen": cached_input_tokens,
        "cache_creation_input_tokens_seen": cache_creation_input_tokens,
    }


async def _record_model_audit(
    *,
    context: dict[str, Any],
    stage: str,
    provider: ModelProvider,
    model: str,
    token_before: dict[str, int],
    findings_count: int | None = None,
    conflict_score: int | None = None,
    decision: str | None = None,
    accepted_findings_count: int | None = None,
    model_resolution: ModelResolution | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    installation_id = cast(int, context["installation_id"])
    review_id = cast(int, context["review_id"])
    input_tokens_after = int(context.get("input_tokens", 0))
    output_tokens_after = int(context.get("output_tokens", 0))
    total_tokens_after = int(context.get("tokens_used", 0))
    input_delta = max(0, input_tokens_after - token_before["input_tokens"])
    output_delta = max(0, output_tokens_after - token_before["output_tokens"])
    total_delta = max(0, total_tokens_after - token_before["tokens_used"])
    metadata: dict[str, Any] = {
        "llm_usage": _llm_usage_since(context, token_before),
    }
    if model_resolution is not None:
        metadata["model_resolution"] = model_resolution.as_metadata()
    if extra_metadata:
        metadata.update(extra_metadata)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            ReviewModelAudit(
                review_id=review_id,
                installation_id=installation_id,
                run_id=cast(str, context["run_id"]),
                stage=stage,
                provider=provider,
                model=model,
                prompt_version=PROMPT_VERSION,
                input_tokens=input_delta,
                output_tokens=output_delta,
                total_tokens=total_delta,
                findings_count=findings_count,
                accepted_findings_count=accepted_findings_count,
                conflict_score=conflict_score,
                decision=decision,
                metadata_json=metadata,
            )
        )
        await session.commit()


def _build_challenger_prompt(primary: ReviewResult, *, final_summary_hint: str) -> str:
    payload = primary.model_dump(mode="json")
    return (
        "You are a challenger reviewer. Verify whether each finding is valid and significant.\n"
        "Drop weak findings, keep strong findings, and optionally refine wording.\n"
        "Return your full result with the submit_review tool.\n\n"
        f"Original summary hint: {final_summary_hint}\n\n"
        f"Primary findings JSON:\n{payload}"
    )


def _build_tie_break_prompt(primary: ReviewResult, challenger: ReviewResult) -> str:
    primary_json = primary.model_dump(mode="json")
    challenger_json = challenger.model_dump(mode="json")
    return (
        "You are a tie-break adjudicator.\n"
        "Compare primary and challenger findings and return the best final set.\n"
        "Prioritize correctness and evidence quality over quantity.\n"
        "Return your result with submit_review.\n\n"
        f"Primary:\n{primary_json}\n\n"
        f"Challenger:\n{challenger_json}"
    )


def _finding_key(finding: Finding) -> tuple[str, int, int, str]:
    return (
        finding.file_path,
        finding.line_start,
        finding.line_end or finding.line_start,
        normalize_for_match(finding.message),
    )


def _calculate_conflict_score(primary: list[Finding], challenger: list[Finding]) -> int:
    primary_keys = {_finding_key(item) for item in primary}
    challenger_keys = {_finding_key(item) for item in challenger}
    union = primary_keys.union(challenger_keys)
    if not union:
        return 0
    overlap = primary_keys.intersection(challenger_keys)
    disagreement = len(union) - len(overlap)
    return int(round((disagreement / len(union)) * 100))


def _has_high_risk_findings(findings: list[Finding], threshold: str) -> bool:
    threshold_rank = SEVERITY_RANK.get(threshold, SEVERITY_RANK["high"])
    return any(SEVERITY_RANK.get(item.severity, 0) >= threshold_rank for item in findings)


def _merge_debate_results(
    *,
    primary: ReviewResult,
    challenger: ReviewResult,
    tie_break: ReviewResult | None,
) -> ReviewResult:
    candidates = [primary, challenger]
    if tie_break is not None:
        candidates.append(tie_break)
    votes: dict[tuple[str, int, int, str], list[Finding]] = {}
    for candidate in candidates:
        for finding in candidate.findings:
            votes.setdefault(_finding_key(finding), []).append(finding)
    required_votes = 2 if len(candidates) >= 2 else 1
    merged: list[Finding] = []
    for key, finding_votes in votes.items():
        if len(finding_votes) >= required_votes or SEVERITY_RANK.get(finding_votes[0].severity, 0) >= SEVERITY_RANK["high"]:
            best = max(finding_votes, key=lambda item: item.confidence)
            merged.append(best.model_copy(deep=True))
    merged.sort(key=lambda item: (SEVERITY_RANK[item.severity], item.confidence), reverse=True)
    summary = primary.summary if primary.summary else "Automated review completed."
    return ReviewResult(findings=merged, summary=summary)


def extract_tool_usage_by_file(messages: list[dict[str, object]]) -> set[str]:
    touched_paths: set[str] = set()
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            block_type: str | None = None
            tool_input: dict[str, object] | None = None
            if isinstance(block, dict):
                block_type = str(block.get("type", ""))
                maybe_input = block.get("input")
                if isinstance(maybe_input, dict):
                    tool_input = maybe_input
            else:
                block_type = str(getattr(block, "type", ""))
                maybe_input = getattr(block, "input", None)
                if isinstance(maybe_input, dict):
                    tool_input = maybe_input
            if block_type != "tool_use" or tool_input is None:
                continue
            candidate = tool_input.get("path") or tool_input.get("file_path")
            if isinstance(candidate, str) and candidate.strip():
                touched_paths.add(candidate.strip())
    return touched_paths


def extract_tool_call_history(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    history: list[dict[str, object]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            block_type: str | None = None
            block_name: str | None = None
            tool_input: dict[str, object] | None = None
            if isinstance(block, dict):
                block_type = str(block.get("type", ""))
                block_name = str(block.get("name", "")) if block.get("name") is not None else None
                maybe_input = block.get("input")
                if isinstance(maybe_input, dict):
                    tool_input = maybe_input
            else:
                block_type = str(getattr(block, "type", ""))
                name_value = getattr(block, "name", None)
                block_name = str(name_value) if isinstance(name_value, str) else None
                maybe_input = getattr(block, "input", None)
                if isinstance(maybe_input, dict):
                    tool_input = maybe_input
            if block_type != "tool_use" or not block_name or tool_input is None:
                continue
            history.append({"name": block_name, "input": tool_input})
    return history


def cross_check_tool_evidence(
    findings: list[Finding],
    tool_call_history: list[dict[str, object]],
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    actual_tool_names = {
        str(call.get("name"))
        for call in tool_call_history
        if isinstance(call.get("name"), str)
    }
    actual_tool_signatures = {
        f"{call.get('name')}:{_stable_tool_input_repr(call.get('input'))}"
        for call in tool_call_history
        if isinstance(call.get("name"), str)
    }

    accepted: list[Finding] = []
    rejected: list[tuple[Finding, str]] = []
    for finding in findings:
        if finding.evidence != "tool_verified":
            accepted.append(finding)
            continue
        claimed_calls = set(finding.evidence_tool_calls or [])
        if not claimed_calls:
            rejected.append((finding, "missing claimed tool calls"))
            continue
        missing = {
            claim
            for claim in claimed_calls
            if claim not in actual_tool_names and claim not in actual_tool_signatures
        }
        if missing:
            rejected.append((finding, f"claimed tool calls not in history: {sorted(missing)}"))
            continue
        accepted.append(finding)
    return accepted, rejected


def cross_check_fact_ids(
    findings: list[Finding],
    known_fact_ids: set[str],
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    accepted: list[Finding] = []
    rejected: list[tuple[Finding, str]] = []
    for finding in findings:
        if finding.evidence == "verified_fact" and finding.evidence_fact_id not in known_fact_ids:
            rejected.append((finding, f"unknown fact id: {finding.evidence_fact_id}"))
            continue
        accepted.append(finding)
    return accepted, rejected


def _stable_tool_input_repr(raw_input: object) -> str:
    if not isinstance(raw_input, dict):
        return "{}"
    parts = [f"{key}={raw_input[key]}" for key in sorted(raw_input.keys())]
    return ",".join(parts)


def _confidence_bucket(value: int) -> str:
    if value >= 95:
        return "95-100"
    if value >= 80:
        return "80-94"
    if value >= 60:
        return "60-79"
    if value >= 40:
        return "40-59"
    return "0-39"


def _warn_if_carriage_returns(fetched_files: dict[str, str]) -> None:
    with_carriage_return = [path for path, content in fetched_files.items() if "\r" in content]
    if with_carriage_return:
        logger.warning(
            "Found carriage returns in normalized fetched_files paths=%s",
            with_carriage_return[:10],
        )


def _repair_findings_from_files(
    findings: list[Finding],
    fetched_files: dict[str, str],
    *,
    commentable_lines: set[tuple[str, int]] | None,
    window: int,
) -> list[Finding]:
    repaired: list[Finding] = []
    for finding in findings:
        repaired.append(
            _repair_finding(
                finding,
                fetched_files,
                commentable_lines=commentable_lines,
                window=window,
            )
        )
    return repaired


def _repair_finding(
    finding: Finding,
    fetched_files: dict[str, str],
    *,
    commentable_lines: set[tuple[str, int]] | None,
    window: int,
) -> Finding:
    file_content = fetched_files.get(finding.file_path)
    if file_content is None:
        return finding

    lines = file_content.split("\n")
    start_line = finding.line_start
    end_line = finding.line_end or finding.line_start
    if not (1 <= start_line <= len(lines)):
        return finding

    actual = lines[start_line - 1]
    if normalize_for_match(actual) == normalize_for_match(finding.target_line_content):
        finding.target_line_content = actual
        return finding

    line_span = max(0, end_line - start_line)
    search_start = max(1, start_line - window)
    search_end = min(len(lines), end_line + window)
    matched_line = _find_normalized_line(lines, finding.target_line_content, search_start, search_end)
    if matched_line is None:
        return finding

    new_end_line = min(len(lines), matched_line + line_span)
    if commentable_lines is not None and not _is_commentable_range(finding.file_path, matched_line, new_end_line, commentable_lines):
        return finding

    finding.line_start = matched_line
    finding.line_end = new_end_line
    finding.target_line_content = lines[matched_line - 1]
    return finding


def _find_normalized_line(lines: list[str], target_line_content: str, start_line: int, end_line: int) -> int | None:
    normalized_target = normalize_for_match(target_line_content)
    for line_no in range(start_line, end_line + 1):
        if normalize_for_match(lines[line_no - 1]) == normalized_target:
            return line_no
    return None


def _is_commentable_range(
    path: str,
    start_line: int,
    end_line: int,
    commentable_lines: set[tuple[str, int]],
) -> bool:
    return all((path, line_no) in commentable_lines for line_no in range(start_line, end_line + 1))


def _summarize_target_line_mismatch_subtypes(
    dropped: list[tuple[Finding, DropReason, str]],
    fetched_files: dict[str, str],
    *,
    commentable_lines: set[tuple[str, int]] | None,
    window: int,
) -> dict[str, int]:
    subtype_counts = {
        "target_line_mismatch_crlf": 0,
        "target_line_mismatch_whitespace": 0,
        "target_line_mismatch_wrong_line": 0,
        "target_line_mismatch_hallucinated": 0,
    }
    for finding, reason, _ in dropped:
        if reason != "target_line_mismatch":
            continue
        subtype = _target_line_mismatch_subtype(
            finding,
            fetched_files,
            commentable_lines=commentable_lines,
            window=window,
        )
        subtype_counts[subtype] = subtype_counts.get(subtype, 0) + 1
    return subtype_counts


def _target_line_mismatch_subtype(
    finding: Finding,
    fetched_files: dict[str, str],
    *,
    commentable_lines: set[tuple[str, int]] | None,
    window: int,
) -> str:
    file_content = fetched_files.get(finding.file_path)
    if file_content is None:
        return "target_line_mismatch_hallucinated"
    lines = file_content.split("\n")
    line_no = finding.line_start
    if not (1 <= line_no <= len(lines)):
        return "target_line_mismatch_hallucinated"

    actual = lines[line_no - 1]
    if finding.target_line_content.replace("\r\n", "\n").replace("\r", "\n") == actual:
        return "target_line_mismatch_crlf"
    if normalize_for_match(actual) == normalize_for_match(finding.target_line_content):
        return "target_line_mismatch_whitespace"

    end_line = finding.line_end or line_no
    search_start = max(1, line_no - window)
    search_end = min(len(lines), end_line + window)
    matched_line = _find_normalized_line(lines, finding.target_line_content, search_start, search_end)
    if matched_line is not None and (
        commentable_lines is None or _is_commentable_range(finding.file_path, matched_line, matched_line, commentable_lines)
    ):
        return "target_line_mismatch_wrong_line"
    return "target_line_mismatch_hallucinated"


def _repair_retry_feedback(
    dropped: list[tuple[Finding, DropReason, str]],
    fetched_files: dict[str, str],
    *,
    window: int,
) -> str:
    lines = [
        "These findings were dropped because target_line_content did not match file content.",
        "Return ONLY repaired findings that remain valid. Omit discarded findings.",
        "For each repaired finding, provide corrected line_start/line_end and exact target_line_content from snippets.",
    ]
    for index, (finding, _, detail) in enumerate(dropped[:20], start=1):
        snippet = _render_file_snippet(
            file_path=finding.file_path,
            line_start=finding.line_start,
            line_end=finding.line_end or finding.line_start,
            fetched_files=fetched_files,
            window=window,
        )
        lines.extend(
            [
                "",
                f"Finding {index}",
                f"file: {finding.file_path}",
                f"your_line_start: {finding.line_start}",
                f"your_line_end: {finding.line_end or finding.line_start}",
                f"drop_detail: {detail}",
                f"your_target_line_content: {finding.target_line_content}",
                f"your_message: {finding.message}",
                "actual_snippet:",
                snippet,
            ]
        )
    return "\n".join(lines)


def _render_file_snippet(
    *,
    file_path: str,
    line_start: int,
    line_end: int,
    fetched_files: dict[str, str],
    window: int,
) -> str:
    content = fetched_files.get(file_path)
    if content is None:
        return "  <file content unavailable>"
    file_lines = content.split("\n")
    if not file_lines:
        return "  <file is empty>"
    start = max(1, line_start - window)
    end = min(len(file_lines), line_end + window)
    out: list[str] = []
    for line_no in range(start, end + 1):
        out.append(f"  {line_no}: {file_lines[line_no - 1]}")
    return "\n".join(out)


def _build_repo_segments(frameworks: list[str], prompt_additions: str | None) -> list[str]:
    segments: list[str] = []
    if frameworks:
        segments.append(f"Detected frameworks: {', '.join(sorted(frameworks))}.")
    if prompt_additions:
        segments.append(f"Repository additions: {prompt_additions.strip()}")
    return segments


def extract_review_comment_ids(review_response: dict[str, object]) -> list[int | None]:
    comments = review_response.get("comments")
    if not isinstance(comments, list):
        return []
    comment_ids: list[int | None] = []
    for comment in comments:
        if not isinstance(comment, dict):
            comment_ids.append(None)
            continue
        raw_id = comment.get("id")
        comment_ids.append(int(raw_id) if isinstance(raw_id, int) else None)
    return comment_ids
