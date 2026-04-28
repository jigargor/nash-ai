"""Rule model + default registry for the analyzer.

``RuleRegistry`` lets callers extend the analyzer at runtime — useful
for the MCP server where the client can register repo-specific rules
between analysis passes without forking the codebase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.review.external.models import FindingCategory, FindingSeverity


@dataclass(frozen=True, slots=True)
class PatternRule:
    """A single regex-based finding rule."""

    rule_id: str
    category: FindingCategory
    severity: FindingSeverity
    title: str
    pattern: re.Pattern[str]
    confidence: float
    allowed_suffixes: tuple[str, ...] = ()
    exclude_example_paths: bool = True


_DEFAULT_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        rule_id="secret.hardcoded_credential",
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
        rule_id="security.unsafe_eval_user_input",
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
        rule_id="best-practice.wildcard_cors",
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
        rule_id="performance.n_plus_one_in_loop",
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
        rule_id="performance.blocking_sleep",
        category="performance",
        severity="high",
        title="Blocking sleep detected in request-time code",
        pattern=re.compile(r"time\.sleep\(\s*[1-9]\d*", re.IGNORECASE),
        confidence=0.84,
        allowed_suffixes=(".py",),
    ),
    PatternRule(
        rule_id="best-practice.dangerous_inner_html",
        category="best-practice",
        severity="high",
        title="Potential unsafe HTML injection sink",
        pattern=re.compile(r"dangerouslySetInnerHTML", re.IGNORECASE),
        confidence=0.86,
        allowed_suffixes=(".ts", ".tsx", ".js", ".jsx"),
    ),
)


@dataclass(slots=True)
class RuleRegistry:
    """Mutable collection of analyzer rules."""

    rules: list[PatternRule] = field(default_factory=list)

    def register(self, rule: PatternRule) -> None:
        if any(existing.rule_id == rule.rule_id for existing in self.rules):
            raise ValueError(f"Rule '{rule.rule_id}' is already registered")
        self.rules.append(rule)

    def unregister(self, rule_id: str) -> bool:
        before = len(self.rules)
        self.rules = [rule for rule in self.rules if rule.rule_id != rule_id]
        return len(self.rules) != before

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.rules)

    @classmethod
    def with_defaults(cls) -> "RuleRegistry":
        return cls(rules=list(_DEFAULT_RULES))


def default_registry() -> RuleRegistry:
    """Return a fresh registry pre-loaded with the built-in rules."""

    return RuleRegistry.with_defaults()
