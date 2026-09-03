"""Harness metrics — anchoring, suggestions, severity, groundedness, golden match."""

from __future__ import annotations

from collections import Counter
from typing import Any

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def finding_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    try:
        expected_line = int(expected["line_start"])
        actual_line = int(actual["line_start"])
    except (KeyError, TypeError, ValueError):
        return False
    if expected.get("file_path") != actual.get("file_path"):
        return False
    if abs(expected_line - actual_line) > 3:
        return False
    if expected.get("category") and actual.get("category"):
        if expected["category"] != actual["category"]:
            return False
    exp_sev = str(expected.get("severity") or "")
    act_sev = str(actual.get("severity") or "")
    if exp_sev in SEVERITY_ORDER and act_sev in SEVERITY_ORDER:
        if abs(SEVERITY_ORDER[exp_sev] - SEVERITY_ORDER[act_sev]) > 1:
            return False
    return True


def golden_scores(
    expected_findings: list[dict[str, Any]], predicted_findings: list[dict[str, Any]]
) -> dict[str, Any]:
    matched: set[int] = set()
    tp = 0
    severity_exact = 0
    severity_off_by_one = 0
    severity_off_by_two_plus = 0
    if not expected_findings:
        return {
            "tp": 0,
            "fp": len(predicted_findings),
            "fn": 0,
            "precision": 0.0 if predicted_findings else 1.0,
            "recall": 1.0,
            "clean_case": True,
            "clean_with_fp": bool(predicted_findings),
            "severity_calibration": 1.0 if not predicted_findings else 0.0,
            "severity_exact": 0,
            "severity_off_by_one": 0,
            "severity_off_by_two_plus": 0,
        }
    for expected in expected_findings:
        for idx, predicted in enumerate(predicted_findings):
            if idx in matched:
                continue
            if finding_matches(expected, predicted):
                matched.add(idx)
                tp += 1
                exp_sev = SEVERITY_ORDER.get(str(expected.get("severity") or ""), None)
                act_sev = SEVERITY_ORDER.get(str(predicted.get("severity") or ""), None)
                if exp_sev is not None and act_sev is not None:
                    delta = abs(exp_sev - act_sev)
                    if delta == 0:
                        severity_exact += 1
                    elif delta == 1:
                        severity_off_by_one += 1
                    else:
                        severity_off_by_two_plus += 1
                break
    fp = len(predicted_findings) - len(matched)
    fn = len(expected_findings) - tp
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": safe_div(tp, tp + fp),
        "recall": safe_div(tp, tp + fn),
        "clean_case": False,
        "clean_with_fp": False,
        # exact = 1.0, off-by-one = 0.5 credit, off-by-two+ = 0; unmatched expected = 0.
        "severity_calibration": safe_div(
            severity_exact + 0.5 * severity_off_by_one, len(expected_findings)
        ),
        "severity_exact": severity_exact,
        "severity_off_by_one": severity_off_by_one,
        "severity_off_by_two_plus": severity_off_by_two_plus,
    }


def anchoring_metrics(
    findings: list[dict[str, Any]],
    files_at_head: dict[str, str],
    commentable_lines: set[tuple[str, int]] | list[tuple[str, int]],
) -> dict[str, Any]:
    commentable = set(commentable_lines)
    exact = 0
    in_diff = 0
    total = len(findings)
    for finding in findings:
        path = str(finding.get("file_path") or "")
        line = int(finding.get("line_start") or 0)
        target = finding.get("target_line_content")
        content = files_at_head.get(path)
        if content is not None and line >= 1:
            lines = content.split("\n")
            if line <= len(lines) and target is not None and lines[line - 1] == target:
                exact += 1
        if (path, line) in commentable:
            in_diff += 1
    return {
        "total": total,
        "exact": exact,
        "in_diff": in_diff,
        "exact_rate": safe_div(exact, total),
        "in_diff_rate": safe_div(in_diff, total),
    }


def suggestion_apply_metrics(
    findings: list[dict[str, Any]],
    files_at_head: dict[str, str],
) -> dict[str, Any]:
    """GitHub-exact splice + optional tree-sitter + non-noop."""
    from importlib import import_module

    get_parser = None
    try:
        pack = import_module("tree_sitter_language_pack")
        get_parser = getattr(pack, "get_parser", None)
    except Exception:
        get_parser = None

    try:
        from app.agent.languages import EXT_TO_LANGUAGE as lang_map
    except Exception:  # pragma: no cover - harness runs without api on path
        lang_map = {"py": "python", "ts": "typescript", "tsx": "tsx", "js": "javascript"}

    with_suggestion = 0
    applies = 0
    parses = 0
    non_noop = 0
    for finding in findings:
        suggestion = finding.get("suggestion")
        if not suggestion:
            continue
        with_suggestion += 1
        path = str(finding.get("file_path") or "")
        content = files_at_head.get(path)
        if content is None:
            continue
        lines = content.split("\n")
        start = int(finding.get("line_start") or 0)
        end = int(finding.get("line_end") or start)
        if start < 1 or end < start or end > len(lines):
            continue
        applies += 1
        replaced = "\n".join(lines[start - 1 : end])
        if suggestion.strip() and suggestion.strip() != replaced.strip():
            non_noop += 1
        new_content = "\n".join(lines[: start - 1] + str(suggestion).split("\n") + lines[end:])
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        language = lang_map.get(ext)
        if not language or get_parser is None:
            parses += 1
            continue
        try:
            parser = get_parser(language)
            tree = parser.parse(new_content.encode("utf-8"))
            root = tree.root_node
            has_error = getattr(root, "has_error", False)
            if callable(has_error):
                has_error = has_error()
            if not has_error:
                parses += 1
        except Exception:
            pass
    return {
        "with_suggestion": with_suggestion,
        "applies_cleanly": applies,
        "parses": parses,
        "non_noop": non_noop,
        "apply_rate": safe_div(applies, with_suggestion),
        "parse_rate": safe_div(parses, with_suggestion),
        "fix_proxy_rate": safe_div(non_noop, with_suggestion),
    }


def severity_distribution(findings: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(f.get("severity") or "unknown") for f in findings))


def groundedness_proxy(findings: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(findings)
    vendor = sum(1 for f in findings if f.get("is_vendor_claim"))
    unverified_vendor = sum(
        1
        for f in findings
        if f.get("is_vendor_claim") and f.get("evidence") not in {"tool_verified", "verified_fact"}
    )
    inference = sum(1 for f in findings if f.get("evidence") == "inference")
    return {
        "total": total,
        "vendor_claims": vendor,
        "vendor_claims_unverified": unverified_vendor,
        "inference_count": inference,
        "vendor_unverified_rate": safe_div(unverified_vendor, total),
        "groundedness_proxy": 1.0 - safe_div(unverified_vendor + inference * 0.25, max(total, 1)),
    }


def compute_run_metrics(
    *,
    report: dict[str, Any],
    files_at_head: dict[str, str],
    commentable_lines: list[tuple[str, int]] | set[tuple[str, int]],
    expected_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = report.get("result") or {}
    findings = list(result.get("findings") or [])
    drops = list(report.get("drops") or [])
    pipeline_errors = list(report.get("pipeline_errors") or [])
    tool_trace = list(report.get("tool_trace") or [])
    debug = report.get("debug_artifacts") or {}
    metrics: dict[str, Any] = {
        "pipeline_errors": len(pipeline_errors),
        "pipeline_error_messages": pipeline_errors,
        "degraded_stages": list(report.get("exceptions") or []),
        "finding_count": len(findings),
        "generated_findings": int(debug.get("generated_findings") or len(findings)),
        "drop_count": len(drops),
        "drop_reasons": dict(
            Counter(str(d.get("reason") or "unknown") for d in drops if isinstance(d, dict))
        ),
        "drop_reasons_by_stage": debug.get("drop_reasons") or {},
        "severity_distribution": severity_distribution(findings),
        "anchoring": anchoring_metrics(findings, files_at_head, commentable_lines),
        "suggestions": suggestion_apply_metrics(findings, files_at_head),
        "groundedness": groundedness_proxy(findings),
        "tool_trace": {
            "calls": len(tool_trace),
            "failed": sum(1 for t in tool_trace if isinstance(t, dict) and not t.get("success")),
            "by_tool": dict(Counter(str(t.get("tool_name")) for t in tool_trace if isinstance(t, dict))),
        },
        "tokens_used": report.get("tokens_used", 0),
        "input_tokens": report.get("input_tokens", 0),
        "output_tokens": report.get("output_tokens", 0),
        "cached_input_tokens": report.get("cached_input_tokens", 0),
        "cost_usd": report.get("cost_usd"),
        "latency_ms": report.get("latency_ms", 0),
        "stage_latencies_ms": report.get("stage_latencies_ms") or {},
        "models_served": report.get("models_served") or [],
        "providers_served": report.get("providers_served") or [],
        "llm_mode": str(debug.get("llm_mode") or "unknown"),
        "diff_cross_check_warnings": len(debug.get("diff_cross_check_warnings") or []),
    }
    if expected_findings is not None:
        metrics["golden"] = golden_scores(expected_findings, findings)
    return metrics
