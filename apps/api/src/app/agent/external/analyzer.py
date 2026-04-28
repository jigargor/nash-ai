"""Compatibility shim exposing the legacy ``analyze_file_content`` API.

The new analyzer lives in :mod:`app.review.external.analyzer`; this
module adapts its output back to the legacy ``CriticalFinding``
dataclass so existing call sites stay compatible.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.review.external.analyzer import analyze_file


@dataclass(slots=True)
class CriticalFinding:
    category: str
    severity: str
    title: str
    message: str
    file_path: str
    line_start: int
    line_end: int
    evidence: dict[str, object]
    confidence: float


def analyze_file_content(path: str, content: str) -> list[CriticalFinding]:
    """Return legacy ``CriticalFinding`` objects for ``path``."""

    matches = analyze_file(path, content)
    return [
        CriticalFinding(
            category=match.category,
            severity=match.severity,
            title=match.title,
            message=match.message,
            file_path=match.file_path,
            line_start=match.line_start,
            line_end=match.line_end,
            evidence={
                "pattern": match.pattern,
                "excerpt": match.excerpt,
                "confidence": match.confidence,
            },
            confidence=match.confidence,
        )
        for match in matches
    ]


__all__ = ["CriticalFinding", "analyze_file_content"]
