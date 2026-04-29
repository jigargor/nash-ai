from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, status

from app.agent.review_chain_graph.graph import compute_branch_flags, run_branching_preview
from app.config import settings

try:  # pragma: no cover - optional dependency
    from langchain_core.runnables import RunnableLambda
    from langserve import add_routes
except Exception:  # pragma: no cover
    RunnableLambda = None
    add_routes = None


def _verify_internal_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_access_key or not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key"
        )
    if not hmac.compare_digest(settings.api_access_key, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key"
        )


def build_review_chain_langserve_router() -> APIRouter:
    router = APIRouter(prefix="/internal/review-chain", tags=["internal-review-chain"])

    @router.post("/branch-preview")
    async def branch_preview(
        payload: dict[str, Any],
        _authorized: None = Depends(_verify_internal_api_key),
    ) -> dict[str, Any]:
        state = compute_branch_flags(
            findings_after_policy=int(payload.get("findings_after_policy", 0)),
            max_mode_enabled=bool(payload.get("max_mode_enabled", False)),
            is_light_review=bool(payload.get("is_light_review", False)),
        )
        return {"state": run_branching_preview(state)}

    return router


def register_optional_langserve_routes(app: FastAPI) -> None:
    if add_routes is None or RunnableLambda is None:
        return
    runnable = RunnableLambda(
        lambda payload: {
            "state": run_branching_preview(
                compute_branch_flags(
                    findings_after_policy=int(payload.get("findings_after_policy", 0)),
                    max_mode_enabled=bool(payload.get("max_mode_enabled", False)),
                    is_light_review=bool(payload.get("is_light_review", False)),
                )
            )
        }
    )
    add_routes(
        app,
        runnable,
        path="/internal/review-chain/langserve",
        dependencies=[Depends(_verify_internal_api_key)],
    )
