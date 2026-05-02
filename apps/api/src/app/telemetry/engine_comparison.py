"""Four-quadrant comparison between LLM findings and rule-engine findings.

Implements the same matching logic as evals/metrics.py:finding_matches()
so that "overlap" means the same as a true-positive match in the eval
harness.

Quadrants
---------
llm_only     — LLM found it; rules did not (LLM-detected, possible FP or nuanced TP)
rule_only     — Rules found it; LLM did not (proxy for LLM false negatives)
overlap       — Both found it (high-confidence TP signal)
missed_by_llm — alias for rule_only (same count; different semantic label)

Design decisions:
- Matching is deterministic: category must be equal, severity within ±1 level,
  file_path identical, line_start within ±line_tolerance (default 3).
- "best-practice" category from the rule engine is treated as equivalent to
  "maintainability" for matching (per quality-model.md §category_mismatch note).
- category_breakdown captures per-category quadrant counts for drill-down.
- Cost fields are optional floats — callers supply them; this module does not
  touch the DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# best-practice → maintainability alias per quality-model.md
_CATEGORY_NORM: dict[str, str] = {"best-practice": "maintainability"}


# ── Public dataclass ───────────────────────────────────────────────────────────


@dataclass
class EngineComparisonReport:
    """Four-quadrant comparison between LLM and rule-engine findings."""

    llm_only_findings: int  # found by LLM but not by rules
    rule_only_findings: int  # found by rules but not by LLM (proxy for LLM FN)
    overlap_findings: int  # found by both
    missed_by_llm: int  # alias for rule_only_findings (same value)
    total_llm_findings: int
    total_rule_findings: int

    # Per-category breakdown: {category: {"llm_only": N, "rule_only": N, "overlap": N}}
    category_breakdown: dict[str, dict[str, int]] = field(default_factory=dict)

    # Cost comparison (callers provide these; None = unknown)
    llm_cost_per_finding_usd: float | None = None
    rule_cost_per_finding_usd: float | None = None  # effectively zero for rule engines


# ── Matching logic (mirrors evals/metrics.py:finding_matches) ──────────────────


def _norm_category(category: str) -> str:
    """Normalize category to canonical form for matching."""
    return _CATEGORY_NORM.get(category, category)


def _severity_matches(a: str, b: str) -> bool:
    if a not in SEVERITY_ORDER or b not in SEVERITY_ORDER:
        return False
    return abs(SEVERITY_ORDER[a] - SEVERITY_ORDER[b]) <= 1


def _finding_matches(
    a: dict[str, object],
    b: dict[str, object],
    *,
    line_tolerance: int,
) -> bool:
    """Return True when two findings describe the same issue.

    Matching criteria (identical to evals/metrics.py:finding_matches):
    - file_path identical
    - |line_start_a − line_start_b| ≤ line_tolerance
    - category equal (after best-practice→maintainability normalization)
    - severity within ±1 level
    """
    raw_a_line = a.get("line_start", 0) or 0
    raw_b_line = b.get("line_start", 0) or 0
    a_line = int(raw_a_line) if isinstance(raw_a_line, (int, float, str)) else 0
    b_line = int(raw_b_line) if isinstance(raw_b_line, (int, float, str)) else 0
    return (
        str(a.get("file_path", "")) == str(b.get("file_path", ""))
        and abs(a_line - b_line) <= line_tolerance
        and _norm_category(str(a.get("category", "")))
        == _norm_category(str(b.get("category", "")))
        and _severity_matches(str(a.get("severity", "")), str(b.get("severity", "")))
    )


# ── Category breakdown helpers ─────────────────────────────────────────────────


def _incr(breakdown: dict[str, dict[str, int]], category: str, slot: str) -> None:
    norm = _norm_category(category)
    cat_counts = breakdown.setdefault(norm, {"llm_only": 0, "rule_only": 0, "overlap": 0})
    cat_counts[slot] = cat_counts.get(slot, 0) + 1


# ── Public comparison function ─────────────────────────────────────────────────


def compare_findings(
    llm_findings: list[dict[str, object]],
    rule_findings: list[dict[str, object]],
    *,
    line_tolerance: int = 3,
    llm_cost_usd: float | None = None,
    rule_cost_usd: float | None = None,
) -> EngineComparisonReport:
    """Compare LLM-generated and rule-engine findings for the same review.

    Uses the same matching algorithm as evals/metrics.py:finding_matches so
    that "overlap" here is consistent with the eval harness definition of a
    true-positive match.

    Args:
        llm_findings:   List of finding dicts from the LLM pipeline.
                        Each dict must have ``file_path``, ``line_start``,
                        ``category``, and ``severity`` keys.
        rule_findings:  List of finding dicts from the rule-based engine
                        (e.g. from ReviewReport.findings serialized to dict).
        line_tolerance: Maximum line-number difference for a match (default 3).
        llm_cost_usd:   Total LLM cost for this review in USD (optional).
        rule_cost_usd:  Total rule-engine cost for this review in USD
                        (typically 0.0 or None for deterministic engines).

    Returns:
        EngineComparisonReport with quadrant counts, category breakdown,
        and optional cost-per-finding metrics.
    """
    category_breakdown: dict[str, dict[str, int]] = {}

    # Greedy matching: for each LLM finding, find the first unmatched rule finding
    matched_rule_indices: set[int] = set()
    llm_only_indices: list[int] = []
    overlap_count = 0

    for llm_finding in llm_findings:
        match_idx: int | None = None
        for rule_idx, rule_finding in enumerate(rule_findings):
            if rule_idx in matched_rule_indices:
                continue
            if _finding_matches(llm_finding, rule_finding, line_tolerance=line_tolerance):
                match_idx = rule_idx
                break

        if match_idx is not None:
            matched_rule_indices.add(match_idx)
            overlap_count += 1
            _incr(category_breakdown, str(llm_finding.get("category", "unknown")), "overlap")
        else:
            llm_only_indices.append(id(llm_finding))
            _incr(category_breakdown, str(llm_finding.get("category", "unknown")), "llm_only")

    # Rule findings not matched by any LLM finding → missed_by_llm
    rule_only_count = 0
    for rule_idx, rule_finding in enumerate(rule_findings):
        if rule_idx not in matched_rule_indices:
            rule_only_count += 1
            _incr(category_breakdown, str(rule_finding.get("category", "unknown")), "rule_only")

    llm_only_count = len(llm_findings) - overlap_count

    # Cost per finding (guard divide-by-zero)
    llm_cost_per_finding: float | None = None
    if llm_cost_usd is not None and len(llm_findings) > 0:
        llm_cost_per_finding = llm_cost_usd / len(llm_findings)

    rule_cost_per_finding: float | None = None
    if rule_cost_usd is not None and len(rule_findings) > 0:
        rule_cost_per_finding = rule_cost_usd / len(rule_findings)

    return EngineComparisonReport(
        llm_only_findings=llm_only_count,
        rule_only_findings=rule_only_count,
        overlap_findings=overlap_count,
        missed_by_llm=rule_only_count,
        total_llm_findings=len(llm_findings),
        total_rule_findings=len(rule_findings),
        category_breakdown=category_breakdown,
        llm_cost_per_finding_usd=llm_cost_per_finding,
        rule_cost_per_finding_usd=rule_cost_per_finding,
    )
