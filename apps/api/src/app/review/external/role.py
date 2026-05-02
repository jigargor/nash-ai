"""External rule-based engine role definition.

The external engine (``apps/api/src/app/review/external/``) is a
deterministic, rule-based static analyser that runs without LLM API calls.
This module documents its purpose and the five distinct roles it plays in
the Nash AI quality pipeline.

The external engine serves as:

1. **High-precision static baseline** — deterministic, low false-positive
   rate.  Rule matches are defined by explicit pattern + severity pairs
   (``apps/api/src/app/review/external/analyzer/rules.py``), so each
   finding can be audited or disabled without retraining.

2. **Cheap regression detector** — runs without LLM API calls, making it
   suitable for continuous pre-screening on every push.  If the engine
   finds nothing, the full LLM pipeline may be skipped for clean-looking
   PRs (configurable via ``EngineConfig``).

3. **False-negative candidate source** — rule findings that the LLM did
   not also flag are proxy candidates for LLM false negatives.  The
   four-quadrant ``compare_findings()`` report in
   ``apps/api/src/app/telemetry/engine_comparison.py`` surfaces these as
   ``missed_by_llm`` / ``rule_only_findings``.  Human auditors can
   promote confirmed misses to ``expected.json`` entries in the eval
   dataset.

4. **Eval dataset generator** — because rule-engine findings are
   deterministic, they can be used to bootstrap eval test cases: if a
   rule fires on a known-good diff and the LLM is expected to also flag
   the issue, the rule finding can be added to
   ``evals/datasets/<case>/expected.json`` as a ground-truth anchor.

5. **Sanity-check layer** — basic issues (hardcoded secrets, SQL
   f-strings, missing HMAC checks) that the LLM should *never* miss.
   When the LLM misses a rule finding in one of these high-severity
   categories, the miss is escalated in severity during human audit and
   fed back as a priority false-negative case.

Category mapping
----------------
The external engine uses ``FindingCategory`` from
``apps/api/src/app/review/external/models.py``, which includes
``"best-practice"`` in addition to the agent-schema categories.
``"best-practice"`` is normalised to ``"maintainability"`` at ingestion
and in the comparison matching logic
(``engine_comparison._CATEGORY_NORM``).

Integration points
------------------
- ``apps/api/src/app/review/external/engine.py`` — ``ReviewEngine`` class
  that orchestrates pre-pass + sharded rule analysis.
- ``apps/api/src/app/review/external/analyzer/rules.py`` — rule definitions
  (``RuleMatch`` emitters).
- ``apps/api/src/app/telemetry/engine_comparison.py`` — four-quadrant LLM
  vs rule-engine comparison report.
- ``apps/api/src/app/telemetry/calibration.py`` — confidence calibration
  scorecard (LLM findings only; the rule engine does not use confidence
  buckets).
"""
