"""Compatibility shim re-exporting planner helpers."""

from __future__ import annotations

from app.review.external.planner import (
    recommended_model_distribution,
    recommended_team_size,
)

__all__ = ["recommended_model_distribution", "recommended_team_size"]
