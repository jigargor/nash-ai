import hashlib
import hmac
import logging
from time import monotonic

from fastapi import APIRouter, Request
from pydantic import ValidationError

from app.config import settings
from app.errors.exceptions import AppError, SecurityError
from app.queue.connection import require_app_redis
from app.webhooks.handlers import (
    queue_pull_request_outcome_classification,
    queue_pull_request_review,
    queue_review_comment_feedback,
    sync_installation_from_webhook,
)
from app.webhooks.schemas import (
    GitHubInstallationWebhookPayload,
    GitHubPullRequestReviewCommentWebhookPayload,
    GitHubPullRequestWebhookPayload,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/github")
async def github_webhook_probe() -> dict[str, str]:
    """URL checks and probes often use GET; GitHub deliveries are signed POST requests."""
    return {"status": "ok", "deliveries": "POST with X-Hub-Signature-256"}


def verify_signature(payload: bytes, signature: str) -> bool:
    expected = (
        "sha256="
        + hmac.new(
            settings.github_webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


_DELIVERY_KEY_PREFIX = "webhook:delivery:"
_DELIVERY_PROCESSING_TTL_SECONDS = 120
_DELIVERY_DONE_TTL_SECONDS = 86400


def _delivery_key(delivery_id: str) -> str:
    return f"{_DELIVERY_KEY_PREFIX}{delivery_id}"


async def _is_duplicate_delivery(request: Request, delivery_id: str) -> bool:
    """Claim the delivery id with a short-lived "processing" marker.

    The marker is upgraded to a 24h "done" marker only after the handler succeeds
    (``_mark_delivery_done``) and removed if it fails (``_release_delivery``), so a
    failed delivery can be redelivered by GitHub.
    """
    if not delivery_id:
        return False
    redis = require_app_redis(request)
    claimed = await redis.set(
        _delivery_key(delivery_id), "processing", ex=_DELIVERY_PROCESSING_TTL_SECONDS, nx=True
    )
    already_seen = not claimed
    if already_seen:
        logger.info("Duplicate webhook delivery skipped delivery_id=%s", delivery_id)
    return already_seen


async def _mark_delivery_done(request: Request, delivery_id: str) -> None:
    if not delivery_id:
        return
    redis = require_app_redis(request)
    await redis.set(_delivery_key(delivery_id), "done", ex=_DELIVERY_DONE_TTL_SECONDS)


async def _release_delivery(request: Request, delivery_id: str) -> None:
    if not delivery_id:
        return
    try:
        redis = require_app_redis(request)
        await redis.delete(_delivery_key(delivery_id))
    except Exception:
        logger.warning(
            "Failed to release webhook delivery claim delivery_id=%s", delivery_id, exc_info=True
        )


@router.post("/github")
async def github_webhook(request: Request) -> dict[str, bool]:
    started_at = monotonic()
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")

    logger.warning(
        "GitHub webhook received event=%s delivery_id=%s payload_size=%s",
        event,
        delivery_id,
        len(payload_bytes),
    )

    if not verify_signature(payload_bytes, signature):
        logger.warning(
            "GitHub webhook signature verification failed event=%s delivery_id=%s",
            event,
            delivery_id,
        )
        raise SecurityError(code="SECURITY_WEBHOOK_SIGNATURE_INVALID", message="Invalid signature")

    if event == "installation":
        if await _is_duplicate_delivery(request, delivery_id):
            return {"ok": True}
        try:
            installation_payload = GitHubInstallationWebhookPayload.model_validate_json(
                payload_bytes
            )
        except ValidationError as exc:
            await _release_delivery(request, delivery_id)
            logger.warning(
                "GitHub installation webhook payload validation failed delivery_id=%s errors=%s",
                delivery_id,
                exc.errors(),
            )
            raise AppError(
                code="VALIDATION_WEBHOOK_PAYLOAD",
                message="Invalid payload",
                status_code=400,
                family="validation",
                retryable=False,
                action="none",
            )

        if installation_payload.action in {
            "created",
            "deleted",
            "suspend",
            "unsuspend",
            "new_permissions_accepted",
        }:
            try:
                await sync_installation_from_webhook(installation_payload)
            except BaseException:
                await _release_delivery(request, delivery_id)
                raise
        else:
            logger.warning(
                "GitHub installation webhook ignored action=%s delivery_id=%s",
                installation_payload.action,
                delivery_id,
            )
        await _mark_delivery_done(request, delivery_id)
        logger.info(
            "Webhook processed delivery_id=%s ack_latency_ms=%s",
            delivery_id,
            int((monotonic() - started_at) * 1000),
        )
        return {"ok": True}

    if event == "pull_request_review_comment":
        try:
            review_comment_payload = GitHubPullRequestReviewCommentWebhookPayload.model_validate_json(
                payload_bytes
            )
        except ValidationError as exc:
            logger.warning(
                "GitHub review_comment webhook payload validation failed delivery_id=%s errors=%s",
                delivery_id,
                exc.errors(),
            )
            raise AppError(
                code="VALIDATION_WEBHOOK_PAYLOAD",
                message="Invalid payload",
                status_code=400,
                family="validation",
                retryable=False,
                action="none",
            )
        if await _is_duplicate_delivery(request, delivery_id):
            return {"ok": True}
        try:
            redis = require_app_redis(request)
            await queue_review_comment_feedback(redis, review_comment_payload)
        except BaseException:
            await _release_delivery(request, delivery_id)
            raise
        await _mark_delivery_done(request, delivery_id)
        logger.info(
            "Webhook processed event=%s delivery_id=%s ack_latency_ms=%s",
            event,
            delivery_id,
            int((monotonic() - started_at) * 1000),
        )
        return {"ok": True}

    if event != "pull_request":
        return {"ok": True}

    try:
        pull_request_payload = GitHubPullRequestWebhookPayload.model_validate_json(payload_bytes)
    except ValidationError as exc:
        logger.warning(
            "GitHub webhook payload validation failed delivery_id=%s errors=%s",
            delivery_id,
            exc.errors(),
        )
        raise AppError(
            code="VALIDATION_WEBHOOK_PAYLOAD",
            message="Invalid payload",
            status_code=400,
            family="validation",
            retryable=False,
            action="none",
        )

    if settings.log_webhook_payloads and settings.environment != "production":
        logger.debug(
            "GitHub webhook payload delivery_id=%s payload=%s",
            delivery_id,
            pull_request_payload.model_dump(mode="json"),
        )

    if pull_request_payload.action in {"opened", "synchronize", "reopened"}:
        redis = require_app_redis(request)
        if await _is_duplicate_delivery(request, delivery_id):
            return {"ok": True}
        try:
            await queue_pull_request_review(redis, pull_request_payload, delivery_id=delivery_id)
        except BaseException:
            await _release_delivery(request, delivery_id)
            raise
        await _mark_delivery_done(request, delivery_id)
    elif pull_request_payload.action == "closed":
        redis = require_app_redis(request)
        await queue_pull_request_outcome_classification(redis, pull_request_payload)
    else:
        logger.warning(
            "GitHub pull_request webhook ignored action=%s delivery_id=%s (only opened/synchronize/reopened/closed are handled)",
            pull_request_payload.action,
            delivery_id,
        )

    logger.info(
        "Webhook processed delivery_id=%s ack_latency_ms=%s",
        delivery_id,
        int((monotonic() - started_at) * 1000),
    )
    return {"ok": True}
