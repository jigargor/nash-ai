from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.config import settings
from app.llm.catalog.loader import baseline_catalog_hash, catalog_as_json, load_baseline_catalog

router = APIRouter(prefix="/api/v1/models", tags=["models"])


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(  # pragma: no cover
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key auth is not configured",
        )
    if not settings.api_access_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Api-Key",
        )


@router.get("/catalog")
def get_models_catalog(
    _: None = Depends(_verify_api_access),
    __: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, object]:
    """Return baseline LLM model catalog with per-provider pricing (USD per 1M tokens).

    Pricing comes from packaged `baseline.yaml` (see docs links in-catalog). Hosted DB is not required.
    """
    catalog = load_baseline_catalog()
    return {
        "version": catalog.version,
        "catalog_hash": baseline_catalog_hash(catalog),
        "sources_note": (
            "Per-model pricing reflects `apps/api/src/app/llm/catalog/baseline.yaml`; "
            "URLs are in model/provider `sources` when present."
        ),
        "catalog": catalog_as_json(catalog),
    }
