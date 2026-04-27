from __future__ import annotations

import json
from functools import lru_cache
from hashlib import sha1
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from app.llm.types import ModelCatalog

CATALOG_PACKAGE = "app.llm.catalog"
BASELINE_FILENAME = "baseline.yaml"


@lru_cache(maxsize=1)
def load_baseline_catalog() -> ModelCatalog:
    raw = _read_baseline_text()
    parsed = yaml.safe_load(raw) or {}
    if not isinstance(parsed, dict):
        raise ValueError("LLM baseline catalog must be a mapping")
    return ModelCatalog.model_validate(parsed)


def baseline_catalog_hash(catalog: ModelCatalog | None = None) -> str:
    active_catalog = catalog or load_baseline_catalog()
    payload = active_catalog.model_dump(mode="json", exclude_none=True)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha1(serialized.encode("utf-8"), usedforsecurity=False).hexdigest()


def catalog_as_json(catalog: ModelCatalog | None = None) -> dict[str, Any]:
    active_catalog = catalog or load_baseline_catalog()
    return active_catalog.model_dump(mode="json")


def known_provider_ids(catalog: ModelCatalog | None = None) -> set[str]:
    active_catalog = catalog or load_baseline_catalog()
    return active_catalog.provider_ids()


def _read_baseline_text() -> str:
    try:
        return resources.files(CATALOG_PACKAGE).joinpath(BASELINE_FILENAME).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        fallback = Path(__file__).parent / BASELINE_FILENAME
        return fallback.read_text(encoding="utf-8")
