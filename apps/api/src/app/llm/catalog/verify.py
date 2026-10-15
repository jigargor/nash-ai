from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.agent.provider_clients import create_openai_compatible_client
from app.config import settings
from app.llm.catalog.loader import load_baseline_catalog
from app.llm.types import ModelCatalog
from app.observability import create_async_anthropic_client


def verify_catalog(catalog: ModelCatalog, *, now: datetime | None = None) -> list[str]:
    checked_at = now or datetime.now(timezone.utc)
    errors: list[str] = []
    known_models = {(record.provider, record.model) for record in catalog.models}

    for record in catalog.models:
        shutdown_at = record.shutdown_at
        if shutdown_at is not None and shutdown_at.tzinfo is None:
            shutdown_at = shutdown_at.replace(tzinfo=timezone.utc)
        if record.status == "unknown" and not record.replacement_candidates:
            errors.append(f"{record.provider}/{record.model}: unknown model has no replacement")
        if (
            shutdown_at is not None
            and shutdown_at <= checked_at
            and record.status != "retired"
        ):
            errors.append(
                f"{record.provider}/{record.model}: shutdown date passed but status is "
                f"{record.status}"
            )
        for replacement in record.replacement_candidates:
            if (record.provider, replacement) not in known_models:
                errors.append(
                    f"{record.provider}/{record.model}: replacement {replacement} is not cataloged"
                )
    return errors


async def verify_live_models(catalog: ModelCatalog) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    summaries: list[str] = []
    provider_keys = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
    }
    for provider, api_key in provider_keys.items():
        if not api_key:
            summaries.append(f"{provider}: skipped (no API key)")
            continue
        try:
            live_ids = await _list_live_model_ids(provider, api_key)
        except Exception as exc:
            errors.append(f"{provider}: models.list failed ({type(exc).__name__})")
            continue
        active_ids = {
            record.model
            for record in catalog.models_for_provider(provider)
            if record.status in {"active", "legacy"}
        }
        missing = sorted(active_ids - live_ids)
        if missing:
            errors.append(f"{provider}: active catalog models absent from models.list: {missing}")
        summaries.append(f"{provider}: {len(live_ids)} live models")
    return errors, summaries


async def _list_live_model_ids(provider: str, api_key: str) -> set[str]:
    if provider == "anthropic":
        anthropic_client = create_async_anthropic_client(api_key)
        try:
            anthropic_page = await anthropic_client.models.list(limit=1000)
            return _model_ids(anthropic_page)
        finally:
            await anthropic_client.close()

    openai_client = create_openai_compatible_client(provider, user_key_override=api_key)
    try:
        openai_page = await openai_client.models.list()
        return _model_ids(openai_page)
    finally:
        await openai_client.close()


def _model_ids(page: object) -> set[str]:
    data = getattr(page, "data", None)
    if not isinstance(data, list):
        return set()
    model_ids: set[str] = set()
    for item in data:
        model_id = getattr(item, "id", None)
        if isinstance(model_id, str) and model_id:
            model_ids.add(model_id.removeprefix("models/"))
    return model_ids


async def _run() -> int:
    catalog = load_baseline_catalog()
    errors = verify_catalog(catalog)
    live_errors, summaries = await verify_live_models(catalog)
    errors.extend(live_errors)

    print(f"Catalog: {len(catalog.models)} models across {len(catalog.providers)} providers")
    for summary in summaries:
        print(f"- {summary}")
    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("OK")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
