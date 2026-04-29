"""Analyzer execution over a single file using a ``RuleRegistry``."""

from __future__ import annotations

import re

from app.review.external.analyzer.rules import RuleRegistry, default_registry
from app.review.external.models import RuleMatch

_SOURCE_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".rs",
    ".sql",
    ".yml",
    ".yaml",
)

_EXAMPLE_PATH_MARKERS: tuple[str, ...] = (
    "/test/",
    "/tests/",
    "/fixtures/",
    "/fixture/",
    "/examples/",
    "/sample/",
    "/samples/",
    "/mocks/",
    "/mock/",
    "/docs/",
)

_PLACEHOLDER_SECRET_PATTERN = re.compile(
    r"(changeme|example|sample|dummy|your_|xxx|todo)",
    re.IGNORECASE,
)


def should_scan_path(path: str) -> bool:
    return path.strip().lower().endswith(_SOURCE_SUFFIXES)


def _looks_like_example_path(path: str) -> bool:
    lowered = f"/{path.strip().lower()}"
    return any(marker in lowered for marker in _EXAMPLE_PATH_MARKERS)


def _line_number_for_index(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _excerpt_at(content: str, start: int, end: int, window: int = 90) -> str:
    snippet_start = max(0, start - window)
    snippet_end = min(len(content), end + window)
    return " ".join(content[snippet_start:snippet_end].strip().split())[:260]


def _is_placeholder_secret(match_text: str) -> bool:
    return bool(_PLACEHOLDER_SECRET_PATTERN.search(match_text))


def analyze_file(
    path: str,
    content: str,
    *,
    registry: RuleRegistry | None = None,
) -> list[RuleMatch]:
    """Return raw ``RuleMatch`` objects for ``path``.

    The caller is responsible for promoting rule matches into
    ``Finding`` objects and applying severity/confidence filters.
    """

    if not should_scan_path(path) or not content.strip():
        return []

    active_registry = registry or default_registry()
    is_example_path = _looks_like_example_path(path)
    lower_path = path.lower()

    matches: list[RuleMatch] = []
    for rule in active_registry:
        if rule.allowed_suffixes and not lower_path.endswith(rule.allowed_suffixes):
            continue
        if is_example_path and rule.exclude_example_paths:
            continue
        for match in rule.pattern.finditer(content):
            match_text = match.group(0)
            if rule.rule_id == "secret.hardcoded_credential" and _is_placeholder_secret(
                match_text
            ):
                continue
            line = _line_number_for_index(content, match.start())
            matches.append(
                RuleMatch(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    severity=rule.severity,
                    title=rule.title,
                    message=f"{rule.title} detected in {path}.",
                    file_path=path,
                    line_start=line,
                    line_end=line,
                    pattern=rule.pattern.pattern,
                    excerpt=_excerpt_at(content, match.start(), match.end()),
                    confidence=rule.confidence,
                )
            )
            break
    return matches
