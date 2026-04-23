import logging
import hashlib
import hmac
from fastapi import APIRouter, Request, HTTPException
from pydantic import ValidationError

from app.config import settings
from app.webhooks.handlers import queue_pull_request_outcome_classification, queue_pull_request_review
from app.webhooks.schemas import GitHubPullRequestWebhookPayload

router = APIRouter()
logger = logging.getLogger(__name__)


def verify_signature(payload: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/github")
async def github_webhook(request: Request) -> dict[str, bool]:
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
        logger.warning("GitHub webhook signature verification failed event=%s delivery_id=%s", event, delivery_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    if event != "pull_request":
        return {"ok": True}

    try:
        payload = GitHubPullRequestWebhookPayload.model_validate_json(payload_bytes)
    except ValidationError as exc:
        logger.warning(
            "GitHub webhook payload validation failed delivery_id=%s errors=%s",
            delivery_id,
            exc.errors(),
        )
        raise HTTPException(status_code=400, detail="Invalid payload")

    if settings.log_webhook_payloads and settings.environment != "production":
        logger.debug("GitHub webhook payload delivery_id=%s payload=%s", delivery_id, payload.model_dump(mode="json"))

    if payload.action in {"opened", "synchronize"}:
        await queue_pull_request_review(request.app.state.redis, payload)
    elif payload.action == "closed":
        await queue_pull_request_outcome_classification(request.app.state.redis, payload)
    else:
        logger.warning(
            "GitHub pull_request webhook ignored action=%s delivery_id=%s (only opened/synchronize/closed are handled)",
            payload.action,
            delivery_id,
        )

    return {"ok": True}
