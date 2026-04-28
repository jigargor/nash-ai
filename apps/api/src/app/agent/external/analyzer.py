from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

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


@dataclass(slots=True)
class PatternRule:
    category: str
    severity: str
    title: str
    pattern: re.Pattern[str]
    confidence: float
    allowed_suffixes: tuple[str, ...] = ()
    exclude_example_paths: bool = True


_SOURCE_SUFFIXES = (
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

_EXAMPLE_PATH_MARKERS = (
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
    r"(changeme|example|sample|dummy|placeholder|your_|xxx|todo)",
    re.IGNORECASE,
)

_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        category="security",
        severity="critical",
        title="Potential hardcoded credential",
        pattern=re.compile(
            r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]([A-Za-z0-9_\-]{20,})['\"]",
            re.IGNORECASE,
        ),
        confidence=0.93,
    ),
    PatternRule(
        category="security",
        severity="high",
        title="Potential unsafe code execution with untrusted input",
        pattern=re.compile(
            r"(exec\(|eval\(|subprocess\.Popen|os\.system)[^\n]{0,100}(request|input|argv|query|params)",
            re.IGNORECASE,
        ),
        confidence=0.9,
        allowed_suffixes=(".py", ".js", ".ts", ".tsx"),
    ),
    PatternRule(
        category="best-practice",
        severity="high",
        title="Wildcard CORS policy in server code",
        pattern=re.compile(
            r"(allow_origins\s*=\s*\[\s*['\"]\*['\"]\s*\]|Access-Control-Allow-Origin[^\n]{0,10}\*)",
            re.IGNORECASE,
        ),
        confidence=0.88,
        allowed_suffixes=(".py", ".ts", ".js"),
    ),
    PatternRule(
        category="performance",
        severity="high",
        title="Potential N+1 request pattern in loop",
        pattern=re.compile(
            r"for\s+[^\n]+:\s*(?:\n[ \t]+[^\n]+){0,4}(requests\.|httpx\.|fetch\()",
            re.IGNORECASE,
        ),
        confidence=0.82,
    ),
    PatternRule(
        category="performance",
        severity="high",
        title="Blocking sleep detected in request-time code",
        pattern=re.compile(r"time\.sleep\(\s*[1-9]\d*", re.IGNORECASE),
        confidence=0.84,
        allowed_suffixes=(".py",),
    ),
    PatternRule(
        category="best-practice",
        severity="high",
        title="Potential unsafe HTML injection sink",
        pattern=re.compile(r"dangerouslySetInnerHTML", re.IGNORECASE),
        confidence=0.86,
        allowed_suffixes=(".ts", ".tsx", ".js", ".jsx"),
    ),
)


def _line_number_for_index(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def should_scan_path(path: str) -> bool:
    lowered = path.strip().lower()
    return lowered.endswith(_SOURCE_SUFFIXES)


def _looks_like_example_path(path: str) -> bool:
    lowered = f"/{path.strip().lower()}"
    return any(marker in lowered for marker in _EXAMPLE_PATH_MARKERS)


def _excerpt_at(content: str, start: int, end: int, window: int = 90) -> str:
    snippet_start = max(0, start - window)
    snippet_end = min(len(content), end + window)
    return " ".join(content[snippet_start:snippet_end].strip().split())[:260]


def _is_placeholder_secret(match_text: str) -> bool:
    return bool(_PLACEHOLDER_SECRET_PATTERN.search(match_text))


def analyze_file_content(path: str, content: str) -> list[CriticalFinding]:
    if not should_scan_path(path) or not content.strip():
        return []
    findings: list[CriticalFinding] = []
    is_example_path = _looks_like_example_path(path)
    lower_path = path.lower()

    for rule in _RULES:
        suffix_filter = rule.allowed_suffixes
        if suffix_filter and not lower_path.endswith(suffix_filter):
            continue
        if is_example_path and rule.exclude_example_paths:
            continue
        for match in rule.pattern.finditer(content):
            match_text = match.group(0)
            if rule.title == "Potential hardcoded credential" and _is_placeholder_secret(match_text):
                continue
            line = _line_number_for_index(content, match.start())
            findings.append(
                CriticalFinding(
                    category=rule.category,
                    severity=rule.severity,
                    title=rule.title,
                    message=f"{rule.title} detected in {path}.",
                    file_path=path,
                    line_start=line,
                    line_end=line,
                    evidence={
                        "pattern": rule.pattern.pattern,
                        "excerpt": _excerpt_at(content, match.start(), match.end()),
                        "confidence": rule.confidence,
                    },
                    confidence=rule.confidence,
                )
            )
            # Avoid flooding with duplicate matches in one file for same rule.
            break
    return findings

