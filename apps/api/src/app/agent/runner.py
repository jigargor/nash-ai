import logging
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from fnmatch import fnmatch
from time import monotonic
from typing import Any, cast

import redis.exceptions as redis_exc
from redis.asyncio import Redis

from app.agent.acknowledgments import extract_todo_fixme_markers
from app.agent.config_cache import get_cached_review_config, set_cached_review_config
from app.agent.constants import PROMPT_VERSION, REPAIR_RETRY_DROP_RATE, REPAIR_SEARCH_WINDOW
from app.agent.context_builder import (
    ContextBundle,
    ContextTelemetry,
    build_context_bundle,
    is_diff_too_large,
)
from app.agent.diff_parser import FileInDiff, parse_diff, right_side_diff_line_set
from app.agent.editor import run_editor
from app.agent.finalize import finalize_review
from app.agent.loop import run_agent
from app.agent.normalization import normalize_for_match
from app.agent.profiler import profile_repo
from app.agent.prompts import build_initial_user_prompt, build_system_prompt, load_verified_fact_ids
from app.agent.review_config import ReviewConfig, load_review_config
from app.agent.schema import DropReason, EditedReview, Finding, ReviewResult
from app.agent.validator import FindingValidator
from app.agent.vendor_detect import auto_tag_vendor_claims
from app.config import settings
from app.db.models import Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.github.client import GitHubClient
from app.github.comments import post_review
from app.observability import record_review_trace
from app.ratelimit import check_and_consume_daily_token_budget, current_daily_token_usage
from app.telemetry.finding_outcomes import seed_pending_finding_outcomes

logger = logging.getLogger(__name__)
FULL_REGENERATE_RETRY_DROP_RATE = 0.50
MIN_RECOVERY_RATIO_FOR_SUCCESS = 0.50
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


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
            "model": review_config.model.name,
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

        if pr.get("draft", False) and not review_config.review_drafts:
            result = ReviewResult(findings=[], summary="Skipped automated review because this pull request is a draft.")
            await _mark_review_done(session_data=result, context=context, status="done", review_config=review_config)
            return
        if is_diff_too_large(diff_text):
            result = ReviewResult(
                findings=[],
                summary="PR is too large for automated review. Please split it into smaller changes and re-run.",
            )
            await post_review(gh, owner, repo, pr_number, head_sha, result)
            await _mark_review_done(session_data=result, context=context, status="done", review_config=review_config)
            return

        files_in_diff, fetched_map, context_bundle, system_prompt, user_prompt = await _assemble_context(
            gh, context, diff_text, review_config
        )
        messages = await run_agent(system_prompt, user_prompt, context, model_name=review_config.model.name)
        result = await finalize_review(
            system_prompt,
            messages,
            context,
            model_name=review_config.model.name,
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
                    model_name=review_config.model.name,
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
                    model_name=review_config.model.name,
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
        result, confidence_dropped = _apply_confidence_threshold(result, threshold)
        result.findings, auto_tag_vendor_rejected = auto_tag_vendor_claims(result.findings)
        known_fact_ids = load_verified_fact_ids()
        result.findings, evidence_tool_rejected = cross_check_tool_evidence(result.findings, tool_call_history)
        result.findings, evidence_fact_rejected = cross_check_fact_ids(result.findings, known_fact_ids)
        evidence_rejections = [*auto_tag_vendor_rejected, *evidence_tool_rejected, *evidence_fact_rejected]
        evidence_rejection_reasons = Counter(reason for _, reason in evidence_rejections)
        draft_result = ReviewResult(findings=list(result.findings), summary=result.summary)
        code_acknowledgments = extract_todo_fixme_markers(fetched_map)
        prior_reviews = await gh.get_pr_reviews_by_bot(owner, repo, pr_number)
        edited_result = await run_editor(
            draft=draft_result,
            pr_context={
                "title": pr.get("title", ""),
                "description": pr.get("body", "") or "",
                "commits": [str((commit.get("commit") or {}).get("message", "")) for commit in commits],
            },
            prior_reviews=prior_reviews,
            code_acknowledgments=code_acknowledgments,
            model_name=review_config.model.name,
        )
        final_result = ReviewResult(findings=edited_result.findings, summary=edited_result.summary)
        final_result = _apply_review_config_filters(final_result, review_config)
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
    input_price = review_config.model.input_per_1m_usd if review_config else Decimal("3.00")
    output_price = review_config.model.output_per_1m_usd if review_config else Decimal("15.00")
    cost = _estimate_cost_usd(
        context.get("input_tokens", 0),
        context.get("output_tokens", 0),
        input_per_1m_usd=input_price,
        output_per_1m_usd=output_price,
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
            review.model = review_config.model.name
        review.findings = session_data.model_dump(mode="json")
        review.debug_artifacts = context.get("debug_artifacts")
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
) -> Decimal:
    input_cost = Decimal(input_tokens) / Decimal(1_000_000) * input_per_1m_usd
    output_cost = Decimal(output_tokens) / Decimal(1_000_000) * output_per_1m_usd
    return (input_cost + output_cost).quantize(Decimal("0.000001"))


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
    context["debug_artifacts"] = {
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
    }


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
