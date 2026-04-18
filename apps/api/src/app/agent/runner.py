from datetime import datetime, timezone
from decimal import Decimal
import logging

from app.agent.context_builder import build_context_bundle, is_diff_too_large
from app.agent.diff_parser import parse_diff
from app.agent.finalize import finalize_review
from app.agent.loop import run_agent
from app.agent.profiler import profile_repo
from app.agent.prompts import build_initial_user_prompt, build_system_prompt
from app.agent.review_config import ReviewConfig, load_review_config
from app.agent.schema import Finding, ReviewResult
from app.agent.validator import FindingValidator
from app.db.models import Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.github.client import GitHubClient
from app.github.comments import post_review

logger = logging.getLogger(__name__)
MODEL_NAME = "claude-sonnet-4-5"


async def run_review(
    review_id: int,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
) -> None:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise RuntimeError(f"Review {review_id} does not exist")
        review.status = "running"
        review.started_at = datetime.now(timezone.utc)
        await session.commit()

    context = {
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

    try:
        gh = await GitHubClient.for_installation(installation_id)
        context["github_client"] = gh

        diff_text = await gh.get_pull_request_diff(owner, repo, pr_number)
        if is_diff_too_large(diff_text):
            result = ReviewResult(
                findings=[],
                summary="PR is too large for automated review. Please split it into smaller changes and re-run.",
            )
            await post_review(gh, owner, repo, pr_number, head_sha, result)
            await _mark_review_done(session_data=result, context=context, status="done")
            return

        files_in_diff = parse_diff(diff_text)
        context_bundle = await build_context_bundle(gh, owner, repo, head_sha, files_in_diff)
        repo_profile = await profile_repo(gh, owner, repo, head_sha)
        review_config = await load_review_config(gh, owner, repo, head_sha)
        system_prompt = build_system_prompt(repo_profile.frameworks, review_config.prompt_additions)
        user_prompt = build_initial_user_prompt(owner, repo, pr_number, context_bundle.rendered)
        messages = await run_agent(system_prompt, user_prompt, context)
        result = await finalize_review(system_prompt, messages, context)

        validator = FindingValidator(context_bundle.fetched_files)
        result, validator_dropped, generated = _validate_result(result, validator)
        retry_triggered = False
        if generated > 0 and len(validator_dropped) > generated * 0.5:
            retry_triggered = True
            feedback = _validation_feedback(validator_dropped)
            logger.warning("Retrying review generation due to high invalid finding rate review_id=%s", review_id)
            retried = await finalize_review(system_prompt, messages, context, validation_feedback=feedback)
            result, validator_dropped, generated = _validate_result(retried, validator)

        threshold = review_config.confidence_threshold or 0.85
        result, confidence_dropped = _apply_confidence_threshold(result, threshold)
        _attach_debug_artifacts(
            context=context,
            generated=generated,
            validator_dropped=validator_dropped,
            confidence_dropped=confidence_dropped,
            retry_triggered=retry_triggered,
            threshold=threshold,
        )
        _log_quality_metrics(
            context=context,
            frameworks=repo_profile.frameworks,
            review_config=review_config,
            generated=generated,
            validator_dropped=validator_dropped,
            confidence_dropped=confidence_dropped,
            posted=len(result.findings),
        )

        await post_review(gh, owner, repo, pr_number, head_sha, result)
        await _mark_review_done(session_data=result, context=context, status="done")
    except Exception as exc:
        logger.exception("Review job failed review_id=%s", review_id)
        await _mark_review_done(
            session_data=ReviewResult(findings=[], summary=f"Review failed: {exc}"),
            context=context,
            status="failed",
        )
        raise


async def _mark_review_done(session_data: ReviewResult, context: dict, status: str) -> None:
    cost = _estimate_cost_usd(context.get("input_tokens", 0), context.get("output_tokens", 0))
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, int(context["installation_id"]))
        review = await session.get(Review, context["review_id"])
        if review is None:
            return
        review.status = status
        review.findings = session_data.model_dump(mode="json")
        review.debug_artifacts = context.get("debug_artifacts")
        review.tokens_used = int(context.get("tokens_used", 0))
        review.cost_usd = cost
        review.completed_at = datetime.now(timezone.utc)
        await session.commit()


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> Decimal:
    input_cost = Decimal(input_tokens) / Decimal(1_000_000) * Decimal("3.00")
    output_cost = Decimal(output_tokens) / Decimal(1_000_000) * Decimal("15.00")
    return (input_cost + output_cost).quantize(Decimal("0.000001"))


def _validate_result(
    result: ReviewResult,
    validator: FindingValidator,
) -> tuple[ReviewResult, list[tuple[Finding, str]], int]:
    valid_findings: list[Finding] = []
    dropped: list[tuple[Finding, str]] = []
    generated = len(result.findings)
    for finding in result.findings:
        is_valid, reason = validator.validate(finding)
        if is_valid:
            valid_findings.append(finding)
            continue
        dropped_reason = reason or "Unknown validation error"
        dropped.append((finding, dropped_reason))
        logger.warning("Dropped finding: %s — %s", dropped_reason, finding.message[:80])
    result.findings = valid_findings
    return result, dropped, generated


def _apply_confidence_threshold(result: ReviewResult, threshold: float) -> tuple[ReviewResult, list[dict[str, object]]]:
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


def _validation_feedback(dropped: list[tuple[Finding, str]]) -> str:
    feedback_lines = ["Previous findings were dropped by validation. Regenerate using exact lines and coherent suggestions."]
    for finding, reason in dropped[:10]:
        feedback_lines.append(
            f"- {finding.file_path}:{finding.line_start}-{finding.line_end or finding.line_start} "
            f"reason={reason} message={finding.message[:120]}"
        )
    return "\n".join(feedback_lines)


def _log_quality_metrics(
    context: dict,
    frameworks: list[str],
    review_config: ReviewConfig,
    generated: int,
    validator_dropped: list[tuple[Finding, str]],
    confidence_dropped: list[dict[str, object]],
    posted: int,
) -> None:
    dropped_by_reason: dict[str, int] = {}
    for _, reason in validator_dropped:
        dropped_by_reason[reason] = dropped_by_reason.get(reason, 0) + 1
    dropped_by_reason["below_confidence_threshold"] = len(confidence_dropped)

    logger.info(
        "Review quality metrics review_id=%s generated=%s validator_dropped=%s confidence_dropped=%s posted=%s threshold=%.2f frameworks=%s "
        "dropped_reasons=%s prompt_version=%s",
        context.get("review_id"),
        generated,
        len(validator_dropped),
        len(confidence_dropped),
        posted,
        review_config.confidence_threshold,
        ",".join(frameworks),
        dropped_by_reason,
        "v2",
    )


def _attach_debug_artifacts(
    context: dict,
    generated: int,
    validator_dropped: list[tuple[Finding, str]],
    confidence_dropped: list[dict[str, object]],
    retry_triggered: bool,
    threshold: float,
) -> None:
    validator_entries = [
        {
            "file_path": finding.file_path,
            "line_start": finding.line_start,
            "line_end": finding.line_end or finding.line_start,
            "reason": reason,
            "message_excerpt": finding.message[:120],
        }
        for finding, reason in validator_dropped
    ]
    context["debug_artifacts"] = {
        "generated_findings_count": generated,
        "validator_dropped": validator_entries,
        "confidence_dropped": confidence_dropped,
        "retry_triggered": retry_triggered,
        "retry_reason": "validator_drop_rate_above_50_percent" if retry_triggered else None,
        "confidence_threshold": threshold,
    }
