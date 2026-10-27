"""Deterministic offline reviewer used when no LLM key is present.

It is NOT a model: it pattern-matches added lines for a handful of well-known
defects so the pipeline (ingestion -> validation -> policy -> dedupe -> delivery ->
metrics) can be exercised end to end at $0. Runs produced with it are labelled
``llm_mode: stub`` everywhere and never count as model quality evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agent.schema import Finding, PRContext, ReviewResult


@dataclass(frozen=True)
class StubRule:
    rule_id: str
    pattern: re.Pattern[str]
    severity: str
    category: str
    message: str
    confidence: int
    replacement: tuple[str, str] | None = None
    extensions: tuple[str, ...] | None = None
    skip_tests: bool = True


# NOTE: Finding.check_evidence_consistency forbids severity=critical without tool-verified
# evidence. The stub never runs tools, so its ceiling is "high" (still within +/-1 of critical
# goldens for the calibration metric).
RULES: list[StubRule] = [
    StubRule(
        "py-sql-fstring",
        re.compile(r"\.execute\(\s*f[\"']|f[\"'].*\b(SELECT|INSERT|UPDATE|DELETE)\b.*\{"),
        "high",
        "security",
        "SQL is built with an f-string, so interpolated values reach the database unescaped. "
        "Use a parameterized query (placeholders + params tuple) instead of string formatting.",
        95,
        None,
        ("py",),
    ),
    StubRule(
        "py-signature-eq",
        re.compile(r"(signature|digest|token|hmac)\w*\s*==\s*|==\s*\w*(signature|digest|expected)"),
        "high",
        "security",
        "Signature/token comparison with == is not constant-time; use hmac.compare_digest so "
        "timing differences cannot leak the expected value.",
        90,
        None,
        ("py",),
    ),
    StubRule(
        "py-eval-exec",
        re.compile(r"(?<![\w.])(eval|exec)\("),
        "high",
        "security",
        "eval/exec on runtime data allows arbitrary code execution. Parse the input explicitly "
        "(ast.literal_eval or a whitelist) instead.",
        90,
        None,
        ("py",),
    ),
    StubRule(
        "shell-true",
        re.compile(r"shell\s*=\s*True"),
        "high",
        "security",
        "shell=True hands the command line to a shell, so any interpolated argument can inject "
        "commands. Pass an argv list with shell=False.",
        90,
        ("shell=True", "shell=False"),
        ("py",),
    ),
    StubRule(
        "verify-false",
        re.compile(r"verify\s*=\s*False"),
        "high",
        "security",
        "TLS verification is disabled, which allows man-in-the-middle interception. Remove "
        "verify=False or pin a CA bundle.",
        92,
        ("verify=False", "verify=True"),
        ("py",),
    ),
    StubRule(
        "hardcoded-secret",
        re.compile(
            r"(?i)(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{12,}[\"']"
            r"|[\"'](sk[_-](live|test)[_-][A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|"
            r"xox[bap]-[A-Za-z0-9-]{20,})[\"']"
            r"|://[^\s:/@\"']+:[^\s/@\"']{6,}@"
        ),
        "high",
        "security",
        "A credential is hard-coded in source. Move it to configuration/environment and rotate "
        "the exposed value.",
        90,
        None,
        None,
    ),
    StubRule(
        "py-bare-except",
        re.compile(r"^\s*except\s*:\s*$"),
        "medium",
        "correctness",
        "A bare except swallows SystemExit/KeyboardInterrupt and hides real failures. Catch "
        "Exception (or the specific errors you expect) and log them.",
        88,
        ("except:", "except Exception:"),
        ("py",),
    ),
    StubRule(
        "react-dangerous-html",
        re.compile(r"dangerouslySetInnerHTML"),
        "high",
        "security",
        "dangerouslySetInnerHTML renders unsanitized markup; if any part of this HTML comes from "
        "user input it is an XSS sink. Sanitize (e.g. DOMPurify) or render as text.",
        88,
        None,
        ("tsx", "jsx", "js", "ts"),
    ),
    StubRule(
        "js-math-random-secret",
        re.compile(r"Math\.random\(\).*(token|secret|nonce|password|id)|(token|secret|nonce).*Math\.random\("),
        "medium",
        "security",
        "Math.random() is not cryptographically secure; use crypto.randomUUID() or "
        "crypto.getRandomValues() for tokens and identifiers.",
        85,
        None,
        ("ts", "tsx", "js", "jsx"),
    ),
    StubRule(
        "ts-any-cast",
        re.compile(r"\bas any\b"),
        "low",
        "maintainability",
        "Casting to any disables type checking for this expression; narrow the type or add an "
        "explicit interface so regressions are caught at compile time.",
        80,
        None,
        ("ts", "tsx"),
    ),
]

_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)(/|$)|\.test\.|\.spec\.|_test\.py$|test_\w+\.py$")


def _ext(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _target_line(pr: PRContext, path: str, line_no: int, diff_content: str) -> str:
    content = pr.files_at_head.get(path)
    if content is None:
        return diff_content
    lines = content.replace("\r\n", "\n").split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return diff_content


def _suggestion_for(rule: StubRule, line: str) -> str | None:
    if rule.replacement is None:
        return None
    old, new = rule.replacement
    if old not in line:
        return None
    return line.replace(old, new, 1)


def stub_findings(pr: PRContext, files_in_diff: list[Any]) -> list[Finding]:
    findings: list[Finding] = []
    for file in files_in_diff:
        path = str(getattr(file, "path", ""))
        if not path or getattr(file, "is_deleted", False):
            continue
        ext = _ext(path)
        is_test = bool(_TEST_PATH.search(path))
        for numbered in getattr(file, "numbered_lines", []):
            if getattr(numbered, "kind", "") != "add" or numbered.new_line_no is None:
                continue
            content = str(numbered.content)
            if "TODO" in content or "FIXME" in content or "nosec" in content:
                continue
            for rule in RULES:
                if rule.extensions is not None and ext not in rule.extensions:
                    continue
                if rule.skip_tests and is_test:
                    continue
                if not rule.pattern.search(content):
                    continue
                line_no = int(numbered.new_line_no)
                target = _target_line(pr, path, line_no, content)
                findings.append(
                    Finding(
                        severity=rule.severity,  # type: ignore[arg-type]
                        category=rule.category,  # type: ignore[arg-type]
                        message=rule.message,
                        file_path=path,
                        line_start=line_no,
                        line_end=None,
                        target_line_content=target,
                        suggestion=_suggestion_for(rule, target),
                        confidence=rule.confidence,
                        evidence="diff_visible",
                    )
                )
                break
    return findings


async def stub_agent_runner(
    system_prompt: str,
    initial_user_message: str,
    context: dict[str, Any],
    *,
    model_name: str,
    provider: str,
) -> list[dict[str, Any]]:
    _ = system_prompt, model_name, provider
    context["llm_mode"] = "stub"
    context["agent_metrics"] = {
        "turn_count": 0,
        "fetch_file_content_calls": 0,
        "first_model_call_latency_ms": 0,
        "provider": "stub",
        "tool_result_tokens": {},
        "tool_result_tokens_by_tool": {},
        "tool_result_calls_by_tool": {},
        "tool_result_tokens_total": 0,
    }
    return [
        {"role": "user", "content": initial_user_message},
        {"role": "assistant", "content": [{"type": "text", "text": "offline stub reviewer"}]},
    ]


async def stub_finalizer(
    system_prompt: str,
    messages: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    model_name: str,
    provider: str,
    **_: Any,
) -> ReviewResult:
    _ = system_prompt, messages, model_name, provider
    pr = context.get("pr_context")
    files_in_diff = context.get("files_in_diff") or []
    if not isinstance(pr, PRContext):
        return ReviewResult(findings=[], summary="Stub reviewer: no PR context available.")
    findings = stub_findings(pr, list(files_in_diff))
    if findings:
        summary = (
            f"Offline stub pass over {len(files_in_diff)} changed files flagged "
            f"{len(findings)} pattern-matched issue(s); see inline comments."
        )
    else:
        summary = (
            f"Offline stub pass over {len(files_in_diff)} changed files found no pattern-matched "
            "issues. This is not a model review."
        )
    return ReviewResult(findings=findings, summary=summary)
