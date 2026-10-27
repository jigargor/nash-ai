import logging
from datetime import UTC, datetime

from arq.connections import ArqRedis
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.agent.review_config import DEFAULT_MODEL_NAME, DEFAULT_MODEL_PROVIDER
from app.config import settings
from app.db.models import (
    FindingOutcome,
    Installation,
    InstallationUser,
    Review,
    User,
    UserProviderKey,
)
from app.db.session import AsyncSessionLocal, set_installation_context
from app.llm.circuit_breaker import is_circuit_open
from app.queue.idempotency import (
    acquire_review_submission_lock,
    release_review_submission_lock,
)
from app.ratelimit import check_installation_review_rate_limit, current_daily_token_usage
from app.webhooks.schemas import (
    GitHubInstallationWebhookPayload,
    GitHubPullRequestReviewCommentWebhookPayload,
    GitHubPullRequestWebhookPayload,
)

logger = logging.getLogger(__name__)

SUPERSEDED_REVIEW_STATUS = "superseded"
_SUPERSEDABLE_STATUSES = ("queued", "running")

SKIP_REVIEW_TAG = "[skip-nash-review]"
FORCE_REVIEW_TAG = "[force-nash-review]"
_REVIEW_ENQUEUE_FAILURE_SUMMARY = (
    "Review failed before execution because the worker job could not be enqueued."
)


async def _persist_skipped_review(
    *,
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
    status: str,
    summary: str,
    account_login: str,
    account_type: str,
) -> int | None:
    """Create a terminal Review row so skips are visible in the dashboard and on check runs."""
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
                )
            )
            await session.flush()
        review = Review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            pr_head_sha=head_sha,
            model=DEFAULT_MODEL_NAME,
            status=status,
            findings={"findings": [], "summary": summary},
            completed_at=datetime.now(UTC),
            debug_artifacts={"skip_reason": status, "summary": summary},
        )
        session.add(review)
        await session.commit()
        return int(review.id)


async def supersede_older_reviews(
    session: AsyncSession,
    *,
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
) -> list[int]:
    """Mark queued/running reviews for older heads of the same PR as superseded.

    Returns the ids of reviews that were superseded. The caller owns the commit.
    """
    stale_reviews = (
        await session.scalars(
            select(Review)
            .where(Review.installation_id == installation_id)
            .where(Review.repo_full_name == repo_full_name)
            .where(Review.pr_number == pr_number)
            .where(Review.pr_head_sha != head_sha)
            .where(Review.status.in_(_SUPERSEDABLE_STATUSES))
        )
    ).all()
    superseded_ids: list[int] = []
    now = datetime.now(UTC)
    for stale in stale_reviews:
        old_sha = str(stale.pr_head_sha or "")
        summary = (
            f"Superseded by a newer push (head {head_sha[:7]}); "
            f"this review of {old_sha[:7]} was not posted."
        )
        stale.status = SUPERSEDED_REVIEW_STATUS
        stale.completed_at = now
        stale.findings = {"findings": [], "summary": summary}
        artifacts = dict(stale.debug_artifacts or {})
        artifacts["superseded_by_head_sha"] = head_sha
        stale.debug_artifacts = artifacts
        superseded_ids.append(int(stale.id))
    if superseded_ids:
        logger.warning(
            "Superseded older reviews installation_id=%s repo=%s pr_number=%s new_head_sha=%s review_ids=%s",
            installation_id,
            repo_full_name,
            pr_number,
            head_sha,
            superseded_ids,
        )
    return superseded_ids


async def _publish_skip_check_run(
    *,
    installation_id: int,
    owner: str,
    repo: str,
    head_sha: str,
    status: str,
    summary: str,
) -> None:
    try:
        from app.github.check_runs import conclusion_for_review_status, upsert_review_check_run
        from app.github.client import GitHubClient

        gh = await GitHubClient.for_installation(installation_id)
        check_status, conclusion = conclusion_for_review_status(status)
        await upsert_review_check_run(
            gh,
            owner=owner,
            repo=repo,
            head_sha=head_sha,
            status=check_status,
            conclusion=conclusion,
            title=f"Review {status}",
            summary=summary,
        )
        await gh.aclose()
    except Exception:
        logger.info(
            "Skip check-run publish failed installation_id=%s repo=%s/%s",
            installation_id,
            owner,
            repo,
            exc_info=True,
        )


async def _resolve_byok_user_for_installation(installation_id: int) -> int | None:
    """Pick a linked user with provider keys for webhook-triggered BYOK runs."""
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        user_github_id = await session.scalar(
            select(User.github_id)
            .join(InstallationUser, InstallationUser.user_id == User.id)
            .join(UserProviderKey, UserProviderKey.user_id == User.id)
            .where(InstallationUser.installation_id == installation_id)
            .where(User.deleted_at.is_(None))
            .order_by(
                case((InstallationUser.role == "admin", 0), else_=1),
                UserProviderKey.last_used_at.desc().nullslast(),
                UserProviderKey.updated_at.desc(),
                User.github_id.asc(),
            )
            .limit(1)
        )
    if user_github_id is None:
        return None
    return int(user_github_id)


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
    from app.ingestion import extract_review_control_tags

    return extract_review_control_tags(f"{title or ''}\n{body or ''}")["force"]


def _pr_text_has_skip_review_tag(title: str | None, body: str | None) -> bool:
    from app.ingestion import extract_review_control_tags

    return extract_review_control_tags(f"{title or ''}\n{body or ''}")["skip"]


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
    redis: ArqRedis,
    payload: GitHubPullRequestWebhookPayload,
    *,
    delivery_id: str = "",
) -> None:
    installation_id = payload.installation.id
    if not settings.enable_reviews:
        logger.warning("Skipping review enqueue because ENABLE_REVIEWS is false")
        return
    byok_user_github_id = await _resolve_byok_user_for_installation(installation_id)
    if not settings.has_llm_api_key_configured() and byok_user_github_id is None:
        logger.warning(
            "Skipping review enqueue: no base LLM API key is configured and no linked BYOK user key found "
            "installation_id=%s",
            installation_id,
        )
        return

    repo_full_name = payload.repository.full_name
    owner, repo_name = repo_full_name.split("/")
    pr_number = payload.pull_request.number
    head_sha = payload.pull_request.head.sha
    pr_title = payload.pull_request.title or ""
    pr_body = payload.pull_request.body or ""
    has_force_tag = _pr_text_has_force_review_tag(pr_title, pr_body)
    has_skip_tag = _pr_text_has_skip_review_tag(pr_title, pr_body)
    if has_skip_tag or has_force_tag:
        logger.warning(
            "PR contains manual review tags skip_tag_present=%s force_tag_present=%s installation_id=%s repo=%s pr_number=%s",
            has_skip_tag,
            has_force_tag,
            installation_id,
            repo_full_name,
            pr_number,
        )
    if has_skip_tag and not has_force_tag:
        summary = f"Review skipped because {SKIP_REVIEW_TAG} is present in the PR title or body."
        logger.warning(
            "Skipping review enqueue because %s is present installation_id=%s repo=%s pr_number=%s",
            SKIP_REVIEW_TAG,
            installation_id,
            repo_full_name,
            pr_number,
        )
        await _persist_skipped_review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            status="skipped",
            summary=summary,
            account_login=payload.repository.owner.login,
            account_type=payload.repository.owner.type,
        )
        await _publish_skip_check_run(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            head_sha=head_sha,
            status="skipped",
            summary=summary,
        )
        return

    provider_for_circuit = await _primary_provider_for_circuit_breaker(installation_id)
    # Check circuit breaker before doing any DB work or enqueue.
    if await is_circuit_open(redis, provider_for_circuit):
        summary = (
            f"Review delayed: AI provider '{provider_for_circuit}' is temporarily unavailable. "
            "Open a new push or use dashboard re-run once the provider recovers."
        )
        logger.warning(
            "Circuit open for provider=%s — persisting skipped review "
            "installation_id=%s repo=%s pr_number=%s",
            provider_for_circuit,
            installation_id,
            repo_full_name,
            pr_number,
        )
        await _persist_skipped_review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            status="skipped",
            summary=summary,
            account_login=payload.repository.owner.login,
            account_type=payload.repository.owner.type,
        )
        await _publish_skip_check_run(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            head_sha=head_sha,
            status="skipped",
            summary=summary,
        )
        try:
            from app.github.client import GitHubClient

            gh = await GitHubClient.for_installation(installation_id)
            await gh.post_issue_comment(
                owner,
                repo_name,
                pr_number,
                "⏳ **Automated review delayed**: the AI provider is temporarily unavailable. "
                "Push a new commit or use dashboard re-run once service recovers (~15 minutes).",
            )
            await gh.aclose()
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
        summary = "Review skipped because the installation hourly review rate limit was reached."
        logger.warning(
            "Skipping review enqueue due to rate limit installation_id=%s repo=%s pr_number=%s",
            installation_id,
            repo_full_name,
            pr_number,
        )
        await _persist_skipped_review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            status="rate_limited",
            summary=summary,
            account_login=payload.repository.owner.login,
            account_type=payload.repository.owner.type,
        )
        await _publish_skip_check_run(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            head_sha=head_sha,
            status="rate_limited",
            summary=summary,
        )
        return
    daily_usage = await current_daily_token_usage(redis, installation_id)
    if daily_usage >= settings.daily_token_budget_per_installation:
        summary = "Review skipped because the installation daily token budget was exhausted."
        logger.warning(
            "Skipping review enqueue due to daily token budget installation_id=%s used=%s limit=%s",
            installation_id,
            daily_usage,
            settings.daily_token_budget_per_installation,
        )
        await _persist_skipped_review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            status="budget_exhausted",
            summary=summary,
            account_login=payload.repository.owner.login,
            account_type=payload.repository.owner.type,
        )
        await _publish_skip_check_run(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            head_sha=head_sha,
            status="budget_exhausted",
            summary=summary,
        )
        return
    if not await acquire_review_submission_lock(
        redis,
        installation_id=installation_id,
        repo_full_name=repo_full_name,
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
    requeued_failed_review = False
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
            .order_by(Review.id.desc())
            .limit(1)
        )
        if existing_review is not None:
            if existing_review.status == "failed":
                existing_review.status = "queued"
                existing_review.started_at = None
                existing_review.completed_at = None
                if delivery_id:
                    requeue_artifacts = dict(existing_review.debug_artifacts or {})
                    requeue_artifacts["delivery_id"] = delivery_id
                    existing_review.debug_artifacts = requeue_artifacts
                await supersede_older_reviews(
                    session,
                    installation_id=installation_id,
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    head_sha=head_sha,
                )
                await session.commit()
                review_id = int(existing_review.id)
                requeued_failed_review = True
            else:
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
        else:
            review = Review(
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                pr_head_sha=head_sha,
                model=DEFAULT_MODEL_NAME,
                status="queued",
                debug_artifacts={"delivery_id": delivery_id} if delivery_id else None,
            )
            session.add(review)
            await session.flush()
            review_id = review.id
            await supersede_older_reviews(
                session,
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                head_sha=head_sha,
            )
            await session.commit()

    try:
        job = await redis.enqueue_job(
            "review_pr",
            review_id,
            installation_id,
            owner,
            repo_name,
            pr_number,
            head_sha,
            user_github_id=byok_user_github_id,
        )
    except Exception:
        # Free the lock so a redelivered webhook is not blocked by a job that never queued.
        await release_review_submission_lock(
            redis,
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
        )
        raise
    if job is None:
        async with AsyncSessionLocal() as session:
            await set_installation_context(session, installation_id)
            review_row = await session.get(Review, review_id)
            if review_row is not None:
                review_row.status = "failed"
                review_row.completed_at = datetime.now(UTC)
                review_row.findings = {"findings": [], "summary": _REVIEW_ENQUEUE_FAILURE_SUMMARY}
                existing_artifacts = dict(review_row.debug_artifacts or {})
                existing_artifacts["terminal_error"] = {
                    "failure_class": "enqueue_failed",
                    "exception_type": "EnqueueJobReturnedNone",
                }
                review_row.debug_artifacts = existing_artifacts
                await session.commit()
        try:
            await release_review_submission_lock(
                redis,
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                head_sha=head_sha,
            )
        except Exception:
            logger.warning(
                "Failed to release submission lock after enqueue failure review_id=%s",
                review_id,
                exc_info=True,
            )
        logger.error(
            "Failed to enqueue review job review_id=%s repo=%s pr_number=%s",
            review_id,
            repo_full_name,
            pr_number,
        )
        return
    logger.warning(
        "Queued review job review_id=%s job_id=%s repo=%s pr_number=%s",
        review_id,
        job.job_id if job else "unknown",
        repo_full_name,
        pr_number,
    )
    if requeued_failed_review:
        logger.warning(
            "Requeued failed review review_id=%s job_id=%s repo=%s pr_number=%s",
            review_id,
            job.job_id if job else "unknown",
            repo_full_name,
            pr_number,
        )


async def queue_review_comment_feedback(
    redis: ArqRedis,
    payload: GitHubPullRequestReviewCommentWebhookPayload,
) -> bool:
    """Enqueue feedback capture for human replies to our review comments.

    Webhooks must ack fast, so the DB work runs in the ARQ worker. Events that cannot
    carry feedback (non-`created`, top-level comments, bot authors) are dropped here.
    Returns True when a job was enqueued.
    """
    comment = payload.comment
    if payload.action != "created" or comment.in_reply_to_id is None:
        logger.info(
            "review_comment webhook not a reply, skipped action=%s comment_id=%s",
            payload.action,
            comment.id,
        )
        return False
    if comment.user is not None and comment.user.type.lower() == "bot":
        return False
    job = await redis.enqueue_job(
        "record_review_comment_feedback",
        payload.model_dump(mode="json"),
    )
    logger.info(
        "Queued review comment feedback installation_id=%s repo=%s pr_number=%s comment_id=%s job_id=%s",
        payload.installation.id,
        payload.repository.full_name,
        payload.pull_request.number,
        comment.id,
        job.job_id if job else "unknown",
    )
    return job is not None


async def record_review_comment_feedback(
    payload: GitHubPullRequestReviewCommentWebhookPayload,
) -> bool:
    """Best-effort, lightweight feedback capture for `pull_request_review_comment` events.

    Only human replies (`created` with `in_reply_to_id`) to a comment we posted are
    considered. We look up the matching `finding_outcomes` row under the payload's
    installation context (RLS), record reply signals, and mark the finding `dismissed`
    when the reply uses a negative marker ("won't fix", "not a bug", "by design") and the
    outcome has not already reached a terminal applied/acknowledged state.

    Heavy classification (commits, line-existence, suggestion apply) stays in the
    existing `classify_pr_outcomes` job. Returns True when a row was updated.
    """
    if payload.action != "created":
        logger.info(
            "review_comment webhook ignored action=%s comment_id=%s",
            payload.action,
            payload.comment.id,
        )
        return False
    parent_comment_id = payload.comment.in_reply_to_id
    if parent_comment_id is None:
        return False
    if payload.comment.user is not None and payload.comment.user.type.lower() == "bot":
        return False

    # Local import avoids a module-level cycle with telemetry -> github client.
    from app.telemetry.finding_outcomes import (
        NEGATIVE_REPLY_MARKERS,
        Outcome,
        _emit_outcome_event,
    )

    installation_id = payload.installation.id
    body = (payload.comment.body or "").lower()
    has_negative_marker = any(marker in body for marker in NEGATIVE_REPLY_MARKERS)
    overridable = {Outcome.PENDING.value, Outcome.IGNORED.value, Outcome.ABANDONED.value}

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        row = (
            await session.execute(
                select(FindingOutcome)
                .join(Review, Review.id == FindingOutcome.review_id)
                .where(Review.installation_id == installation_id)
                .where(Review.repo_full_name == payload.repository.full_name)
                .where(Review.pr_number == payload.pull_request.number)
                .where(FindingOutcome.github_comment_id == parent_comment_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return False

        signals = dict(row.signals or {})
        signals["reply_count"] = int(signals.get("reply_count", 0) or 0) + 1
        signals["last_reply_comment_id"] = payload.comment.id
        previous_outcome = str(row.outcome)
        if has_negative_marker and previous_outcome in overridable:
            row.outcome = Outcome.DISMISSED.value
            row.outcome_confidence = "medium"
            signals["dismissed_via"] = "review_comment_reply"
        row.signals = signals
        flag_modified(row, "signals")
        review_id = int(row.review_id)
        finding_index = int(row.finding_index)
        new_outcome = str(row.outcome)
        await session.commit()

    if new_outcome != previous_outcome:
        _emit_outcome_event(
            review_id=review_id,
            installation_id=installation_id,
            finding_index=finding_index,
            outcome=new_outcome,
            github_comment_id=parent_comment_id,
        )
    logger.info(
        "review_comment feedback recorded installation_id=%s review_id=%s finding_index=%s outcome=%s",
        installation_id,
        review_id,
        finding_index,
        new_outcome,
    )
    return True


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
