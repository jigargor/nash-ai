"""Pattern-based analyzer with a pluggable rule registry."""

from __future__ import annotations

from app.review.external.analyzer.engine import analyze_file, should_scan_path
from app.review.external.analyzer.rules import (
    PatternRule,
    RuleRegistry,
    default_registry,
)

__all__ = [
    "PatternRule",
    "RuleRegistry",
    "analyze_file",
    "default_registry",
    "should_scan_path",
]
