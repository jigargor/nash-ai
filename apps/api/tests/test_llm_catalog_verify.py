from datetime import datetime, timezone

from app.llm.catalog.loader import load_baseline_catalog
from app.llm.catalog.verify import verify_catalog


def test_baseline_catalog_passes_static_verification() -> None:
    catalog = load_baseline_catalog()

    assert verify_catalog(
        catalog,
        now=datetime(2026, 9, 2, tzinfo=timezone.utc),
    ) == []


def test_verify_catalog_rejects_unknown_model_without_replacement() -> None:
    catalog = load_baseline_catalog().model_copy(deep=True)
    model = catalog.models[0]
    model.status = "unknown"
    model.replacement_candidates = []

    errors = verify_catalog(catalog)

    assert any("unknown model has no replacement" in error for error in errors)
