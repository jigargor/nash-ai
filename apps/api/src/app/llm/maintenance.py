from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

from app.db.models import LLMModelCatalogSnapshot, LLMModelHealth
from app.db.session import AsyncSessionLocal
from app.llm.catalog.loader import baseline_catalog_hash, catalog_as_json, load_baseline_catalog
from app.llm.providers import get_provider_adapter, registered_provider_ids

logger = logging.getLogger(__name__)


async def refresh_llm_catalog_snapshot(*, fetch_source_hashes: bool = False) -> str:
    catalog = load_baseline_catalog()
    version_hash = baseline_catalog_hash(catalog)
    source_hashes = await _source_hashes(catalog_as_json(catalog), enabled=fetch_source_hashes)
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(
            select(LLMModelCatalogSnapshot).where(LLMModelCatalogSnapshot.version_hash == version_hash)
        )
        if existing is None:
            session.add(
                LLMModelCatalogSnapshot(
                    version_hash=version_hash,
                    catalog_json=catalog_as_json(catalog),
                    source_hashes=source_hashes,
                    promoted_at=datetime.now(timezone.utc),
                )
            )
        await session.commit()
    return version_hash


async def refresh_llm_model_health() -> None:
    catalog = load_baseline_catalog()
    provider_ids = registered_provider_ids()
    async with AsyncSessionLocal() as session:
        for record in catalog.models:
            if record.provider not in provider_ids:
                continue
            adapter = get_provider_adapter(record.provider)
            check = await adapter.health_check(record.model)
            row = await session.scalar(
                select(LLMModelHealth).where(
                    LLMModelHealth.provider == record.provider,
                    LLMModelHealth.model == record.model,
                )
            )
            if row is None:
                row = LLMModelHealth(provider=record.provider, model=record.model)
                session.add(row)
            row.provider_status = "active" if check.ok else "disabled"
            row.circuit_open = not check.ok
            row.failure_class = check.failure_class
            row.last_success_at = datetime.now(timezone.utc) if check.ok else row.last_success_at
            row.last_checked_at = datetime.now(timezone.utc)
            row.latency_ms = check.latency_ms
            row.metadata_json = check.details
        await session.commit()


async def refresh_llm_catalog(ctx: dict[str, Any] | None = None) -> None:
    del ctx
    version_hash = await refresh_llm_catalog_snapshot(fetch_source_hashes=False)
    await refresh_llm_model_health()
    logger.info("LLM catalog maintenance completed version_hash=%s", version_hash)


async def _source_hashes(catalog_json: dict[str, Any], *, enabled: bool) -> dict[str, str]:
    urls: set[str] = set()
    for provider in catalog_json.get("providers", []):
        if isinstance(provider, dict):
            _collect_urls(provider.get("docs"), urls)
    for model in catalog_json.get("models", []):
        if isinstance(model, dict):
            _collect_urls(model.get("sources"), urls)
    if not enabled:
        return {url: hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest() for url in sorted(urls)}

    hashes: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for url in sorted(urls):
            try:
                response = await client.get(url)
                response.raise_for_status()
                hashes[url] = hashlib.sha1(response.text.encode("utf-8"), usedforsecurity=False).hexdigest()
            except Exception as exc:
                hashes[url] = f"fetch_failed:{type(exc).__name__}"
    return hashes


def _collect_urls(raw_sources: object, urls: set[str]) -> None:
    if not isinstance(raw_sources, dict):
        return
    for value in raw_sources.values():
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            urls.add(value)
