import logging
from datetime import UTC, datetime

from arq.connections import ArqRedis
from sqlalchemy import select

from app.agent.review_config import DEFAULT_MODEL_NAME, DEFAULT_MODEL_PROVIDER
from app.config import settings
from app.db.models import Installation, Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.llm.circuit_breaker import is_circuit_open
from app.queue.idempotency import acquire_review_submission_lock
from app.ratelimit import check_installation_review_rate_limit, current_daily_token_usage
from app.webhooks.schemas import GitHubInstallationWebhookPayload, GitHubPullRequestWebhookPayload

logger = logging.getLogger(__name__)

SKIP_REVIEW_TAG = "[skip-nash-review]"
FORCE_REVIEW_TAG = "[force-nash-review]"


async def _primary_provider_for_circuit_breaker(installation_id: int) -> str:
    """Choose provider for pre-enqueue circuit checks, without touching secret values."""
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        latest_provider = await session.scalar(
            select(Review.model_provider)
            .where(Review.installation_id == installation_id)
            .where(Review.model_provider.is_not(None))
            .order_by(Review.id.desc())
            .limit(1)
        )
    if isinstance(latest_provider, str) and latest_provider.strip():
        return latest_provider.strip().lower()
    return DEFAULT_MODEL_PROVIDER


def _pr_text_has_force_review_tag(title: str | None, body: str | None) -> bool:
    combined = f"{title or ''}\n{body or ''}".lower()
    return FORCE_REVIEW_TAG in combined


def _pr_text_has_skip_review_tag(title: str | None, body: str | None) -> bool:
    combined = f"{title or ''}\n{body or ''}".lower()
    return SKIP_REVIEW_TAG in combined


async def sync_installation_from_webhook(payload: GitHubInstallationWebhookPayload) -> None:
    installation_id = payload.installation.id
    account = payload.installation.account
    account_login = account.login if account is not None else f"installation-{installation_id}"
    account_type = account.type if account is not None else "Unknown"
    suspended_at = datetime.now(UTC) if payload.action in {"deleted", "suspend"} else None

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        installation = await session.scalar(
            select(Installation).where(Installation.installation_id == installation_id)
        )
        if installation is None:
            session.add(
                Installation(
                    installation_id=installation_id,
                    account_login=account_login,
                    account_type=account_type,
                    suspended_at=suspended_at,
                )
            )
        else:
            installation.account_login = account_login
            installation.account_type = account_type
            installation.suspended_at = suspended_at
        await session.commit()

    logger.warning(
        "Synced GitHub App installation action=%s installation_id=%s account=%s active=%s",
        payload.action,
        installation_id,
        account_login,
        suspended_at is None,
    )


async def queue_pull_request_review(
    redis: ArqRedis, payload: GitHubPullRequestWebhookPayload
) -> None:
    if not settings.enable_reviews:
        logger.warning("Skipping review enqueue because ENABLE_REVIEWS is false")
        return
    if not settings.has_llm_api_key_configured():
        logger.warning(
            "Skipping review enqueue: ENABLE_REVIEWS is true but no LLM API key is set "
            "(configure ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)"
        )
        return

    installation_id = payload.installation.id
    repo_full_name = payload.repository.full_name
    owner, repo_name = repo_full_name.split("/")
    pr_number = payload.pull_request.number
    head_sha = payload.pull_request.head.sha
    pr_title = payload.pull_request.title or ""
    pr_body = payload.pull_request.body or ""

    if not _pr_text_has_force_review_tag(pr_title, pr_body) and _pr_text_has_skip_review_tag(
        pr_title, pr_body
    ):
        logger.warning(
            "Skipping review enqueue: PR title/body contains %s (override with %s) installation_id=%s repo=%s pr_number=%s",
            SKIP_REVIEW_TAG,
            FORCE_REVIEW_TAG,
            installation_id,
            repo_full_name,
            pr_number,
        )
        return

    provider_for_circuit = await _primary_provider_for_circuit_breaker(installation_id)
    # Check circuit breaker before doing any DB work or enqueue.
    if await is_circuit_open(redis, provider_for_circuit):
        logger.warning(
            "Circuit open for provider=%s — posting delay comment instead of enqueuing "
            "installation_id=%s repo=%s pr_number=%s",
            provider_for_circuit,
            installation_id,
            repo_full_name,
            pr_number,
        )
        try:
            from app.github.client import GitHubClient

            gh = await GitHubClient.for_installation(installation_id)
            await gh.post_issue_comment(
                owner,
                repo_name,
                pr_number,
                "⏳ **Automated review delayed**: the AI provider is temporarily unavailable. "
                "This review will retry automatically once service recovers (~15 minutes).",
            )
        except Exception:
            logger.warning(
                "Failed to post circuit-open comment installation_id=%s pr=%s",
                installation_id,
                pr_number,
            )
        return

    logger.warning(
        "PR webhook parsed installation_id=%s repo=%s pr_number=%s head_sha=%s",
        installation_id,
        repo_full_name,
        pr_number,
        head_sha,
    )
    is_allowed = await check_installation_review_rate_limit(
        redis,
        installation_id,
        limit=settings.reviews_per_hour_limit,
    )
    if not is_allowed:
        logger.warning(
            "Skipping review enqueue due to rate limit installation_id=%s repo=%s pr_number=%s",
            installation_id,
            repo_full_name,
            pr_number,
        )
        return
    daily_usage = await current_daily_token_usage(redis, installation_id)
    if daily_usage >= settings.daily_token_budget_per_installation:
        logger.warning(
            "Skipping review enqueue due to daily token budget installation_id=%s used=%s limit=%s",
            installation_id,
            daily_usage,
            settings.daily_token_budget_per_installation,
        )
        return
    if not await acquire_review_submission_lock(
        redis,
        installation_id=installation_id,
        pr_number=pr_number,
        head_sha=head_sha,
    ):
        logger.warning(
            "Skipping duplicate review enqueue via submission lock installation_id=%s repo=%s pr_number=%s head_sha=%s",
            installation_id,
            repo_full_name,
            pr_number,
            head_sha,
        )
        return
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        installation = await session.scalar(
            select(Installation).where(Installation.installation_id == installation_id)
        )
        if installation is None:
            session.add(
                Installation(
                    installation_id=installation_id,
                    account_login=payload.repository.owner.login,
                    account_type=payload.repository.owner.type,
                )
            )
            await session.flush()
        elif installation.suspended_at is not None:
            installation.account_login = payload.repository.owner.login
            installation.account_type = payload.repository.owner.type
            installation.suspended_at = None
            await session.flush()

        existing_review = await session.scalar(
            select(Review)
            .where(Review.installation_id == installation_id)
            .where(Review.repo_full_name == repo_full_name)
            .where(Review.pr_number == pr_number)
            .where(Review.pr_head_sha == head_sha)
            .where(Review.status != "failed")
            .order_by(Review.id.desc())
            .limit(1)
        )
        if existing_review is not None:
            existing_review_id = existing_review.id
            await session.rollback()
            logger.warning(
                "Skipping duplicate review enqueue for installation_id=%s repo=%s pr_number=%s head_sha=%s existing_review_id=%s",
                installation_id,
                repo_full_name,
                pr_number,
                head_sha,
                existing_review_id,
            )
            return

        review = Review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            pr_head_sha=head_sha,
            model=DEFAULT_MODEL_NAME,
            status="queued",
        )
        session.add(review)
        await session.flush()
        review_id = review.id
        await session.commit()

    job = await redis.enqueue_job(
        "review_pr",
        review_id,
        installation_id,
        owner,
        repo_name,
        pr_number,
        head_sha,
    )
    logger.warning(
        "Queued review job review_id=%s job_id=%s repo=%s pr_number=%s",
        review_id,
        job.job_id if job else "unknown",
        repo_full_name,
        pr_number,
    )


async def queue_pull_request_outcome_classification(
    redis: ArqRedis,
    payload: GitHubPullRequestWebhookPayload,
) -> None:
    installation_id = payload.installation.id
    repo_full_name = payload.repository.full_name
    owner, repo_name = repo_full_name.split("/")
    pr_number = payload.pull_request.number
    job = await redis.enqueue_job(
        "classify_pr_outcomes",
        installation_id,
        owner,
        repo_name,
        pr_number,
    )
    logger.warning(
        "Queued outcome classification installation_id=%s repo=%s pr_number=%s job_id=%s",
        installation_id,
        repo_full_name,
        pr_number,
        job.job_id if job else "unknown",
    )
