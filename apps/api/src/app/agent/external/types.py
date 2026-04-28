"""Backward-compatible aliases for the legacy dataclass types.

New call sites should import ``FileDescriptor``, ``PrepassSignals``, and
``PrepassPlan`` from ``app.review.external`` directly.
"""

from __future__ import annotations

from app.review.external.models import (
    FileDescriptor as ExternalFileDescriptor,
    PrepassPlan,
    PrepassSignals,
)

__all__ = ["ExternalFileDescriptor", "PrepassPlan", "PrepassSignals"]
