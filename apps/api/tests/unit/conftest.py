"""Unit-test subtree: no Postgres; override parent session DB migration autouse."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> None:
    """Parent `tests/conftest.py` runs Alembic against Postgres; unit tests skip it."""
    return None
