import hashlib
import hmac
import logging
from time import monotonic

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.config import settings
from app.queue.connection import require_app_redis
from app.webhooks.handlers import (
    queue_pull_request_outcome_classification,
    queue_pull_request_review,
    sync_installation_from_webhook,
)
from app.webhooks.schemas import GitHubInstallationWebhookPayload, GitHubPullRequestWebhookPayload

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
        raise HTTPException(status_code=401, detail="Invalid signature")

    if event == "installation":
        try:
            installation_payload = GitHubInstallationWebhookPayload.model_validate_json(
                payload_bytes
            )
        except ValidationError as exc:
            logger.warning(
                "GitHub installation webhook payload validation failed delivery_id=%s errors=%s",
                delivery_id,
                exc.errors(),
            )
            raise HTTPException(status_code=400, detail="Invalid payload")

        if installation_payload.action in {
            "created",
            "deleted",
            "suspend",
            "unsuspend",
            "new_permissions_accepted",
        }:
            await sync_installation_from_webhook(installation_payload)
        else:
            logger.warning(
                "GitHub installation webhook ignored action=%s delivery_id=%s",
                installation_payload.action,
                delivery_id,
            )
        logger.info(
            "Webhook processed delivery_id=%s ack_latency_ms=%s",
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
        raise HTTPException(status_code=400, detail="Invalid payload")

    if settings.log_webhook_payloads and settings.environment != "production":
        logger.debug(
            "GitHub webhook payload delivery_id=%s payload=%s",
            delivery_id,
            pull_request_payload.model_dump(mode="json"),
        )

    if pull_request_payload.action in {"opened", "synchronize"}:
        redis = require_app_redis(request)
        await queue_pull_request_review(redis, pull_request_payload)
    elif pull_request_payload.action == "closed":
        redis = require_app_redis(request)
        await queue_pull_request_outcome_classification(redis, pull_request_payload)
    else:
        logger.warning(
            "GitHub pull_request webhook ignored action=%s delivery_id=%s (only opened/synchronize/closed are handled)",
            pull_request_payload.action,
            delivery_id,
        )

    logger.info(
        "Webhook processed delivery_id=%s ack_latency_ms=%s",
        delivery_id,
        int((monotonic() - started_at) * 1000),
    )
    return {"ok": True}
