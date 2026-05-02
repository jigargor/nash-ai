"""Canonical category definitions shared across the review pipeline.

This is the single source of truth for finding categories. All pipeline
surfaces (agent schema, external engine models, finalize helpers) import
from here so they stay in sync.
"""

from typing import Literal, get_args

CanonicalCategory = Literal[
    "security",
    "performance",
    "correctness",
    "style",
    "maintainability",
    "best-practice",
]

CATEGORY_ALIASES: dict[str, CanonicalCategory] = {
    "completeness": "maintainability",
    "documentation": "maintainability",
    "docs": "maintainability",
    "reliability": "correctness",
    "testing": "correctness",
}

ALL_CATEGORIES: frozenset[str] = frozenset(get_args(CanonicalCategory))


def normalize_category(raw: str) -> CanonicalCategory:
    """Normalize a raw category string to the canonical form.

    Returns the input unchanged if it is already a known canonical value,
    maps known aliases to their canonical target, and falls back to
    ``"maintainability"`` for unrecognised values.
    """
    lowered = raw.strip().lower()
    if lowered in ALL_CATEGORIES:
        return lowered  # type: ignore[return-value]
    alias = CATEGORY_ALIASES.get(lowered)
    if alias is not None:
        return alias
    return "maintainability"
