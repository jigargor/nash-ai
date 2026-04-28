from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.external.github_public import fetch_file_sample
from app.agent.external.github_public import PublicRepoRef
from app.agent.external.types import ExternalFileDescriptor


@dataclass(slots=True)
class CriticalFinding:
    category: str
    severity: str
    title: str
    message: str
    file_path: str
    evidence: str


_SECURITY_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "Hardcoded secret material",
        "critical",
        re.compile(
            r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
            re.IGNORECASE,
        ),
    ),
    (
        "Unsanitized command execution",
        "critical",
        re.compile(r"(subprocess\.Popen|os\.system|exec\(|eval\().{0,60}(request|input|params)", re.IGNORECASE),
    ),
]

_PERFORMANCE_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "Potential n+1 loop with network call",
        "high",
        re.compile(r"for\s+.+:\s*\n[^\n]*(fetch\(|requests\.|httpx\.)", re.IGNORECASE),
    ),
    (
        "Synchronous sleep in request path",
        "high",
        re.compile(r"time\.sleep\(", re.IGNORECASE),
    ),
]

_BEST_PRACTICE_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "Dangerous React HTML injection",
        "high",
        re.compile(r"dangerouslySetInnerHTML", re.IGNORECASE),
    ),
    (
        "Wildcard CORS in server path",
        "high",
        re.compile(r"allow_origins\s*=\s*\[\s*['\"]\*['\"]\s*\]|Access-Control-Allow-Origin.*\*", re.IGNORECASE),
    ),
]


def _make_finding(
    *,
    category: str,
    severity: str,
    title: str,
    file_path: str,
    content: str,
    match_start: int,
) -> CriticalFinding:
    line_start = max(0, content.rfind("\n", 0, match_start))
    snippet = content[line_start + 1 : line_start + 180].strip()
    return CriticalFinding(
        category=category,
        severity=severity,
        title=title,
        message=f"{title} detected in {file_path}.",
        file_path=file_path,
        evidence=snippet[:250],
    )


def _scan_content(file_path: str, content: str) -> list[CriticalFinding]:
    findings: list[CriticalFinding] = []
    for title, severity, pattern in _SECURITY_PATTERNS:
        match = pattern.search(content)
        if match:
            findings.append(
                _make_finding(
                    category="security",
                    severity=severity,
                    title=title,
                    file_path=file_path,
                    content=content,
                    match_start=match.start(),
                )
            )
    for title, severity, pattern in _PERFORMANCE_PATTERNS:
        match = pattern.search(content)
        if match:
            findings.append(
                _make_finding(
                    category="performance",
                    severity=severity,
                    title=title,
                    file_path=file_path,
                    content=content,
                    match_start=match.start(),
                )
            )
    for title, severity, pattern in _BEST_PRACTICE_PATTERNS:
        match = pattern.search(content)
        if match:
            findings.append(
                _make_finding(
                    category="best_practices",
                    severity=severity,
                    title=title,
                    file_path=file_path,
                    content=content,
                    match_start=match.start(),
                )
            )
    return findings


async def analyze_shard(repo_ref: PublicRepoRef, files: list[ExternalFileDescriptor]) -> list[CriticalFinding]:
    findings: list[CriticalFinding] = []
    for descriptor in files:
        content = await fetch_file_sample(repo_ref, descriptor.path, max_bytes=8000)
        if not content:
            continue
        findings.extend(_scan_content(descriptor.path, content))
    return findings

