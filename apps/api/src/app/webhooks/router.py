import json
import logging
import hashlib
import hmac
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from app.config import settings
from app.webhooks.handlers import handle_pull_request

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_LOGGED_PAYLOAD_CHARS = 4000


def verify_signature(payload: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")

    payload_preview = payload_bytes.decode("utf-8", errors="replace")[:MAX_LOGGED_PAYLOAD_CHARS]
    logger.warning(
        "GitHub webhook received event=%s delivery_id=%s payload_size=%s payload_preview=%s",
        event,
        delivery_id,
        len(payload_bytes),
        payload_preview,
    )

    if not verify_signature(payload_bytes, signature):
        logger.warning("GitHub webhook signature verification failed event=%s delivery_id=%s", event, delivery_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(payload_bytes)

    if event == "pull_request" and payload.get("action") in ("opened", "synchronize"):
        background_tasks.add_task(handle_pull_request, payload)

    return {"ok": True}
