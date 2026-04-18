from datetime import datetime, timezone
from decimal import Decimal
import logging

from app.agent.context_builder import build_context_bundle, is_diff_too_large
from app.agent.diff_parser import parse_diff
from app.agent.finalize import finalize_review
from app.agent.loop import run_agent
from app.agent.prompts import SYSTEM_PROMPT, build_initial_user_prompt
from app.agent.schema import ReviewResult
from app.db.models import Review
from app.db.session import AsyncSessionLocal
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
        review = await session.get(Review, review_id)
        if review is None:
            raise RuntimeError(f"Review {review_id} does not exist")
        review.status = "running"
        review.started_at = datetime.now(timezone.utc)
        await session.commit()

    context = {
        "review_id": review_id,
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

        hunks = parse_diff(diff_text)
        context_bundle = await build_context_bundle(gh, owner, repo, head_sha, hunks)
        user_prompt = build_initial_user_prompt(owner, repo, pr_number, diff_text, context_bundle)
        messages = await run_agent(SYSTEM_PROMPT, user_prompt, context)
        result = await finalize_review(SYSTEM_PROMPT, messages, context)
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
        review = await session.get(Review, context["review_id"])
        if review is None:
            return
        review.status = status
        review.findings = session_data.model_dump(mode="json")
        review.tokens_used = int(context.get("tokens_used", 0))
        review.cost_usd = cost
        review.completed_at = datetime.now(timezone.utc)
        await session.commit()


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> Decimal:
    input_cost = Decimal(input_tokens) / Decimal(1_000_000) * Decimal("3.00")
    output_cost = Decimal(output_tokens) / Decimal(1_000_000) * Decimal("15.00")
    return (input_cost + output_cost).quantize(Decimal("0.000001"))
