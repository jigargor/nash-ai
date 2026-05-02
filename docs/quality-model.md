# Nash AI Quality Model

> **Status:** Working specification — this document defines how Nash AI measures and improves review quality.  
> **Audience:** Engineers working on the agent, eval pipeline, and prompt tuning.

---

## 1. Label Taxonomy

Labels are applied by human auditors (or a calibrated meta-judge model) to individual findings after a review is posted. A single finding gets exactly one primary label. Secondary labels (e.g., `duplicate` + `false_positive`) are allowed when both apply.

---

### `true_positive`

**Definition.** The finding correctly identifies a real defect, vulnerability, or code smell that a competent reviewer would agree warrants fixing or at minimum acknowledging.

**Decision criteria.**
- The issue exists in the code at the pointed line.
- The severity and category assigned are reasonable (within one level; see `severity_mismatch`).
- The finding would not be ignored by a senior engineer on the author's team.
- Use `true_positive` even if the author ultimately chooses not to fix it—developer preference is not a quality signal.

**Worked example.**

```python
# PR diff: apps/api/src/app/webhooks/github.py, line 47
def handle_push(payload: dict) -> None:
    sql = f"INSERT INTO events (repo) VALUES ('{payload['repository']['name']}')"
    await db.execute(sql)
```

*Finding posted by Nash:*
> **[critical / security]** `line 47` — `payload['repository']['name']` is user-controlled and concatenated directly into SQL. Use parameterized queries via SQLAlchemy to prevent injection.

**Label: `true_positive`** — the f-string SQL with untrusted input is a real injection risk; the severity (critical) matches the schema rules (`critical` requires `tool_verified` evidence and the agent called the file-fetch tool).

---

### `false_positive`

**Definition.** The finding describes something that is not actually a problem in the specific context of this PR, even if the pattern it flags looks suspicious in isolation.

**Decision criteria.**
- The concern is resolved by context the agent didn't see (a wrapper function, an upstream validator, a framework guarantee).
- Assign `false_positive` when the finding would receive a 👎 or a "won't fix / not a bug / by design" reply from an engineer familiar with the codebase.
- Do NOT assign `false_positive` simply because the author chose to ignore the comment; use `ignored` outcome data for that.

**Worked example.**

```typescript
// apps/web/src/lib/api-client.ts, line 83
const url = `${process.env.NEXT_PUBLIC_API_URL}/reviews/${reviewId}`;
```

*Finding posted by Nash:*
> **[high / security]** `line 83` — `reviewId` is interpolated into a URL without sanitization; a crafted value could redirect to an unintended endpoint.

**Label: `false_positive`** — `reviewId` is typed as `number` in the TypeScript interface; numeric types cannot contain path-traversal characters. The agent didn't read the calling function's type signature and flagged a non-issue.

---

### `false_negative`

**Definition.** A real issue exists in the reviewed code but Nash did not post any finding for it. False negatives are identified retroactively—by human audit, by a subsequent security review, or by a post-merge bug.

**Decision criteria.**
- The issue is in the diff that was reviewed (not in pre-existing code outside the changed lines, unless the changed lines are the proximate cause).
- The severity would have met the minimum confidence threshold to be posted (≥ 60 confidence, or critical + tool_verified).
- Assign `false_negative` even if the issue was subtle; low-recall is a quality problem.

**Worked example.**

```python
# apps/api/src/app/queue/worker.py, line 112 — PR added this line
await job_queue.enqueue("process_review", review_id=review_id)
```

A human auditor later notices the job was enqueued without checking whether a job for the same `review_id` is already pending—causing duplicate reviews on rapid push events. Nash posted no finding about idempotency.

**Label: `false_negative`** — this is a correctness gap the agent should have caught given the diff context. It becomes an `expected_finding` entry in the eval dataset (`evals/datasets/<case>/expected.json`).

---

### `duplicate`

**Definition.** The finding restates the same issue as another finding in the same review, pointing at the same root cause even if the exact line or wording differs.

**Decision criteria.**
- Both findings share the same root cause, not merely the same category.
- The second finding adds no new information (no additional file, no narrower blame).
- The highest-quality duplicate is relabeled `true_positive`; the rest are `duplicate`.

**Worked example.**

*Nash posts two findings on a PR that adds a new endpoint:*

> **Finding A** `apps/api/src/app/api/reviews.py:34` — Missing HMAC verification before processing webhook body.  
> **Finding B** `apps/api/src/app/api/reviews.py:58` — Webhook handler does not verify the `X-Hub-Signature-256` header.

Both describe the same missing verification in the same handler. Finding A is labeled `true_positive`; Finding B is labeled `duplicate`.

---

### `severity_mismatch`

**Definition.** The finding correctly identifies a real issue, but the assigned severity level is wrong by more than one step on the `critical > high > medium > low` scale.

**Decision criteria.**
- Two-level mismatches (`critical` filed as `low`, or `low` filed as `high`) always qualify.
- One-level mismatches (`high` vs `medium`) are borderline—use your judgment based on exploitability and blast radius.
- The underlying finding is still `true_positive`; use `severity_mismatch` as a secondary label when both apply.

**Worked example.**

```python
# apps/api/src/app/agent/prompts/code_review_v3.py, line 19
SYSTEM_PROMPT = f"Repository: {repo_name}"  # repo_name from .codereview.yml
```

*Finding:* **[critical / security]** — `repo_name` is interpolated into the system prompt; an adversary could inject instructions.

**Label: `severity_mismatch`** (primary: `true_positive`) — prompt injection via `.codereview.yml` is a real risk, but `.codereview.yml` is controlled by the repo owner (trusted), not by PR authors. `high` would be correct; `critical` overstates it.

---

### `category_mismatch`

**Definition.** The finding correctly identifies a real issue, but the assigned category is wrong. For example, a missing index filed under `security` instead of `performance`, or a typo filed as `correctness` instead of `style`.

**Decision criteria.**
- Reference the taxonomy from `apps/api/src/app/agent/schema.py`: `security | performance | correctness | style | maintainability`.
- External engine findings also include `best-practice` (see `apps/api/src/app/review/external/models.py`), which normalizes to `maintainability` at ingestion.
- Miscategorized findings inflate or deflate per-category metrics; label them even when the root finding is valid.

**Worked example.**

```typescript
// apps/web/src/hooks/use-reviews.ts, line 44
const [reviews, setReviews] = useState<Review[]>([]);
useEffect(() => {
  fetchReviews().then(setReviews);
}, []);  // no abort controller, no cleanup
```

*Finding:* **[medium / security]** — `useEffect` data-fetch lacks cleanup; stale state could expose data from a previous user session.

**Label: `category_mismatch`** (primary: `true_positive`) — missing cleanup causes memory leaks and race conditions (`correctness` or `maintainability`), not a security issue. The session-isolation framing is speculative.

---

### `actionable_but_weak`

**Definition.** The finding is technically correct but does not meet the bar for posting as a review comment. The issue is too obvious, too minor, too noisy given the PR's scope, or is already caught by a linter the team has configured.

**Decision criteria.**
- A senior reviewer would react with "yeah, and?" or "the linter handles this."
- The finding triggers reviewer fatigue without improving code safety or clarity.
- Distinguish from `false_positive`: the issue IS real, it just doesn't warrant a comment.
- Typical triggers: style nits below the agreed severity floor, variable-naming suggestions, whitespace issues, imports covered by `ruff` or `eslint`.

**Worked example.**

```python
# apps/api/src/app/github/client.py, line 201
import os
import sys
import json
import re
```

*Finding:* **[low / style]** `line 201` — Imports are not sorted alphabetically; `json` should precede `os`.

**Label: `actionable_but_weak`** — `ruff` enforces import ordering; this will fail CI automatically. Posting it as a review comment is noise.

---

### `correct_but_not_worth_posting`

**Definition.** The observation is factually accurate but is not a problem—it is intentional design, a deliberate trade-off already documented, or the "fix" would make the code worse.

**Decision criteria.**
- Unlike `actionable_but_weak`, this label is for findings where the observation itself carries no action implication.
- Common triggers: pointing out that a function is long when it is intentionally a single-responsibility aggregator; noting that a magic number exists when it is an industry-standard constant.
- Ask: would a thoughtful author respond "yes, we know, that's intentional"?

**Worked example.**

```python
# apps/api/src/app/agent/runner.py, line 88
MAX_ITERATIONS = 10
```

*Finding:* **[low / maintainability]** `line 88` — Magic number `10` should be extracted to a named constant.

**Label: `correct_but_not_worth_posting`** — `MAX_ITERATIONS = 10` **is** the named constant. The finding mistakes the constant definition for a magic-number usage.

---

## 2. Metric Definitions

All metrics are scoped per `(prompt_version, model, provider)` unless stated otherwise. Computed at benchmark time from `BenchmarkResult` rows and at production time from `FindingOutcome` + `Review` rows.

---

### Precision

```
Precision = TP / (TP + FP)
```

**What it measures.** Of all findings the model posted, what fraction were genuinely useful?  
**Target.** ≥ 0.75 (3 in 4 findings should be valid); alert if < 0.65.  
**How to compute.**
- Eval: sum `BenchmarkResult.true_positives` and `BenchmarkResult.false_positives` across all rows for a `run_id`, then divide.
- Production: requires human labeling. Proxy: treat `dismissed` outcome (with negative signal) as FP and `applied_directly + applied_modified + acknowledged` as TP. Use `summarize_finding_outcomes()` in `apps/api/src/app/telemetry/finding_outcomes.py`.

---

### Recall

```
Recall = TP / (TP + FN)
```

**What it measures.** Of all real issues in the reviewed code, what fraction did the model catch?  
**Target.** ≥ 0.60 for high/critical severity issues; ≥ 0.40 overall (low-severity FNs are more tolerable).  
**How to compute.**
- Eval: `BenchmarkResult.true_positives / (BenchmarkResult.true_positives + BenchmarkResult.false_negatives)`.
- `evals/run_eval.py` computes this using `evals/metrics.py:evaluate_case()`, which matches predictions against `expected.json` by `(file_path, line_start ± 3, category, severity ± 1 level)`.

---

### Clean-case FP rate

```
Clean-case FP rate = Clean cases with ≥1 FP / Total clean cases
```

**What it measures.** How often does the model raise a false alarm on a PR that has no real issues? This is the "false positive rate on good code."  
**Target.** ≤ 0.10 (at most 1 in 10 clean PRs gets a spurious comment).  
**How to compute.**
- Eval: `EvalTotals.clean_cases_with_fp / EvalTotals.clean_cases` — tracked directly in `evals/metrics.py:EvalTotals`.
- `evals/run_eval.py` emits `fp_rate` in the output JSON under `metrics`.

---

### Anchor validity

```
Anchor validity = Findings with correct (file, line) anchor / Total findings posted
```

**What it measures.** Are findings pointing at the right place in the diff? An anchoring error makes an otherwise valid finding unactionable.  
**Target.** ≥ 0.95 — almost all comments should land on the right line.  
**How to compute.**
- Production: `ReviewModelAudit.accepted_findings_count / ReviewModelAudit.findings_count` per stage (the editor stage drops findings for `target_line_mismatch`, `line_out_of_range`, `line_not_in_diff`—see `DropReason` in `apps/api/src/app/agent/schema.py`). Anchor validity ≈ `1 − (drop_count / total_count)` for anchor-related drop reasons.
- Eval: manual spot-check of `Finding.file_path`, `Finding.line_start`, and `Finding.target_line_content` against the diff.

---

### Schema validity

```
Schema validity = Findings passing Pydantic validation / Total raw findings generated
```

**What it measures.** Structured output reliability—does the model produce well-formed `Finding` objects every time?  
**Target.** ≥ 0.99; a schema failure means a finding is lost entirely.  
**How to compute.**
- Production: the agent validates each finding with `Finding.model_validate()` from `apps/api/src/app/agent/schema.py`. Log validation errors at `ERROR` level including `review_id`. Compute `1 − (validation_error_count / total_raw_findings)` from structured logs.
- `ReviewModelAudit.findings_count` (raw) vs `ReviewModelAudit.accepted_findings_count` (passed editor) gives an upper-bound proxy; not identical to schema validity alone.

---

### Cost per useful finding

```
Cost per useful finding = Total LLM cost (USD) / (Applied + Acknowledged findings)
```

**What it measures.** Economic efficiency—how much do we spend per finding that actually changed or was explicitly noted by the developer?  
**Target.** ≤ $0.15 / useful finding on Sonnet; ≤ $0.60 on Opus.  
**How to compute.**
- Numerator: sum `Review.cost_usd` for all reviews in the window.
- Denominator: count `FindingOutcome.outcome` in `{applied_directly, applied_modified, acknowledged}` for those reviews. Available from `summarize_finding_outcomes()`.
- `BenchmarkResult.cost_per_tp_usd` tracks this for eval runs.

---

### Useful rate

```
Useful rate = (Applied + Acknowledged) / Total classified findings
```

**What it measures.** What fraction of posted findings led to meaningful developer action?  
**Target.** ≥ 0.35; below 0.20 is a signal the model is noisy.  
**How to compute.**
- `summarize_finding_outcomes()` returns `global_metrics.useful_rate` directly.
- Breakdown by `severity`, `category`, `confidence_bucket`, `model`, `provider`, and `prompt_version` available from the same function's `breakdowns` dict.

---

### Dismiss rate

```
Dismiss rate = Dismissed / Total classified findings
```

**What it measures.** Developer rejection rate—findings explicitly dismissed via 👎, "won't fix," or "not a bug" replies.  
**Target.** ≤ 0.20; a high dismiss rate indicates false positives or off-topic comments.  
**How to compute.**
- `summarize_finding_outcomes()` returns `global_metrics.dismiss_rate`.
- Signal sources for `dismissed` classification: `NEGATIVE_REACTIONS = {"-1", "confused"}` and `NEGATIVE_REPLY_MARKERS = {"won't fix", "not a bug", "by design"}` in `apps/api/src/app/telemetry/finding_outcomes.py`.

---

### Ignore rate

```
Ignore rate = Ignored / Total classified findings
```

**What it measures.** The fraction of findings that were neither acted on nor explicitly dismissed—they simply didn't generate any engagement. High ignore rate is subtler than dismiss rate: it may mean the finding was too minor, poorly worded, or posted too late in the PR lifecycle.  
**Target.** ≤ 0.35; investigate when ignore rate exceeds dismiss rate by more than 2×.  
**How to compute.**
- `summarize_finding_outcomes()` returns `global_metrics.ignore_rate`.
- `ignored` is assigned when: PR merged and line still exists, no positive reactions, no explicit dismissal; or PR open > 14 days with no engagement.

---

## 3. Existing Foundations Reference

### `.cursor/rules/80-findings-first-review-output.mdc` — Findings-first review contract

This rule defines the output format that all findings must follow:
- **Severity levels**: `critical | high | medium | low` — these map directly to `Finding.severity` in the Pydantic schema.
- **Evidence requirement**: every finding must cite file/path location and a changed-line anchor. This is the origin of the `anchor validity` metric.
- **Suggestion blocks**: findings should include `suggestion` code blocks for one-click commit. Presence of a suggestion is used in `detect_suggestion_apply()` to classify `applied_directly` outcomes.
- **Lead with material risk**: style/readability only after correctness/security/performance. This ordering is enforced by the editor stage.

### `apps/api/src/app/agent/schema.py` — Agent Finding schema

The canonical Pydantic model for agent-generated findings. Key fields and constraints:

| Field | Type | Constraint |
|---|---|---|
| `severity` | `"critical"\|"high"\|"medium"\|"low"` | `critical` requires `evidence="tool_verified"` |
| `category` | `"security"\|"performance"\|"correctness"\|"style"\|"maintainability"` | |
| `evidence` | `"tool_verified"\|"diff_visible"\|"verified_fact"\|"inference"` | `inference` caps confidence at 75 |
| `confidence` | `int 0–100` | **95–100**: tool-verified, no counter-arg; **80–94**: strong diff evidence; **60–79**: plausible unverified; **40–59**: speculative (critical only); **< 40**: do not submit |
| `verified_via_tool` | `bool` | True when a tool call touched the file |
| `suggestion` | `str \| None` | Code block for one-click GitHub apply |
| `target_line_content` | `str` | Exact content of `line_start` at HEAD — used for anchor validation |

`DropReason` literals in the schema control editor-stage rejection: `target_line_mismatch`, `line_out_of_range`, `syntax_invalid_suggestion`, `incoherent_suggestion`, `line_not_in_diff`, `file_not_in_context`.

### `apps/api/src/app/telemetry/finding_outcomes.py` — Outcome classification

`Outcome` enum values and their semantics:

| Outcome | Meaning |
|---|---|
| `applied_directly` | Suggestion applied verbatim (exact match or bot co-author commit) |
| `applied_modified` | Finding addressed but with developer edits (near/modified patch match) |
| `acknowledged` | Developer reacted positively (👍/❤️/🚀) or replied positively |
| `dismissed` | Developer rejected (👎/😕 or "won't fix"/"not a bug"/"by design" reply) |
| `ignored` | PR merged/closed; finding unaddressed, no engagement |
| `abandoned` | PR closed without merging |
| `superseded` | Line changed by unrelated commit before PR merged |
| `pending` | PR still open, < 14 days since review |

Multi-dimensional breakdowns from `summarize_finding_outcomes()`: severity, category, evidence, confidence_bucket (`0-39 | 40-59 | 60-79 | 80-94 | 95-100`), is_vendor_claim, model, provider, repo, prompt_version.

### `apps/api/src/app/review/external/models.py` — External engine FindingCategory

The external repository review engine uses an extended category set:

```python
FindingCategory = Literal[
    "security", "performance", "correctness",
    "best-practice",   # ← additional vs agent schema
    "maintainability", "style",
]
```

`best-practice` findings are normalized to `maintainability` when ingested by the main review pipeline (Phase 6 target). Until normalization is complete, `category_mismatch` labels on external-engine findings should account for this alias.

### `apps/api/src/app/db/models.py` — Database tables

Three tables are the primary data sources for quality metrics:

- **`FindingOutcome`** — one row per finding per review; stores `outcome`, `outcome_confidence`, and `signals` (JSONB with reactions, replies, commit evidence). Source for production Precision/Recall proxies and Useful/Dismiss/Ignore rates.
- **`ReviewModelAudit`** — one row per pipeline stage per review; stores `findings_count`, `accepted_findings_count`, token usage, cost, `prompt_version`. Source for anchor validity and schema validity proxies, and cost attribution.
- **`BenchmarkResult`** — one row per eval case per benchmark run; stores `true_positives`, `false_positives`, `false_negatives`, `cost_usd`, `cost_per_tp_usd`. Source for offline Precision/Recall/FP-rate and cost metrics.

---

## 4. Label-to-Outcome Mapping

Labels are applied in audit; outcomes are observed in production. They are related but not identical—an outcome is a behavioral signal while a label is a quality judgment.

| Audit Label | Expected `FindingOutcome.outcome` Values | Notes |
|---|---|---|
| `true_positive` | `applied_directly`, `applied_modified`, `acknowledged` | High-quality finding with developer action |
| `true_positive` | `ignored`, `pending` | Valid finding that developer chose not to act on — still TP |
| `false_positive` | `dismissed` (with `NEGATIVE_REACTIONS` or `NEGATIVE_REPLY_MARKERS`) | Strong signal, but verify the dismissal reason |
| `false_positive` | `ignored` | Possible FP — no engagement may mean irrelevant, not wrong |
| `false_negative` | *(no row; finding was never posted)* | Must be identified via human audit or post-merge incident |
| `duplicate` | Any outcome — the `true_positive` sibling carries the useful signal | Duplicates inflate FP denominator |
| `severity_mismatch` | Any outcome | Mismatch may cause under/over-reaction independent of outcome |
| `category_mismatch` | Any outcome | Distorts per-category breakdown metrics |
| `actionable_but_weak` | `ignored` | Likely ignored because it's low-value; confirm by checking engagement |
| `correct_but_not_worth_posting` | `dismissed` or `ignored` | Often dismissed with "not a bug" or silently ignored |

**Important distinction.** `ignored` outcome is ambiguous: it could mean `false_positive`, `actionable_but_weak`, `correct_but_not_worth_posting`, or simply developer inattention. Labels from human audit are required to disambiguate ignore-rate root causes.

---

## 5. Eval Integration

### Ground truth dataset structure

```
evals/
  datasets/
    <case-id>/
      expected.json      # {"findings": [Finding, ...]}
      context/           # snapshot of diff, files, PR metadata
  predictions/
    <prompt-version>/
      <case-id>.json     # {"findings": [Finding, ...]} from model output
  results/
    <prompt-version>.json  # metrics output from run_eval.py
```

`expected.json` is populated from two sources:
1. **True positives from labeled reviews** — findings labeled `true_positive` in production audits, exported via `evals/export_snapshot.py` from `ReviewContextSnapshot` rows.
2. **False negatives added manually** — issues identified post-merge that Nash missed; added directly to `expected.json` as new expected findings.

### Matching logic (`evals/metrics.py`)

A predicted finding matches an expected finding when all of:
- `file_path` is identical
- `abs(line_start_predicted − line_start_expected) ≤ 3`
- `category` is identical
- `abs(SEVERITY_ORDER[predicted] − SEVERITY_ORDER[expected]) ≤ 1`

This tolerates minor line-drift between eval dataset capture and model run, and allows adjacent severity grades (e.g., `high` matching `medium`).

### Running evals

```bash
# From repo root — run against a specific prompt version
cd apps/api && uv run python ../../evals/run_eval.py \
  --prompt-version code_review_v4 \
  --datasets-dir ../../evals/datasets \
  --predictions-dir ../../evals/predictions/code_review_v4 \
  --output ../../evals/results/code_review_v4.json
```

Output includes `precision`, `recall`, `fp_rate` plus per-case breakdowns. Compare versions with `evals/compare.py`.

### Feeding production labels back into evals

1. Human auditor labels a finding `false_negative` → add the missed issue to `evals/datasets/<case-id>/expected.json`.
2. Human auditor labels a finding `true_positive` from a production review → export the review context snapshot and add the finding to a new eval case.
3. Re-run evals after each prompt version change. Gate merges when `recall` drops > 5 pp or `fp_rate` rises > 3 pp from the prior version's baseline.

### Confidence calibration checks

Beyond Precision/Recall, monitor confidence calibration by bucketing:

| Bucket | Expected TP rate |
|---|---|
| 95–100 | ≥ 0.90 |
| 80–94 | ≥ 0.75 |
| 60–79 | ≥ 0.55 |
| 40–59 | ≥ 0.40 (critical-only submissions) |

If the actual TP rate in a bucket consistently underperforms the target, the model is overconfident in that range and the confidence calibration prompt should be tightened.

---

## 6. Quick Reference

### Labels summary

| Label | Real issue? | Worth posting? |
|---|---|---|
| `true_positive` | ✅ | ✅ |
| `false_positive` | ❌ | ❌ |
| `false_negative` | ✅ (missed) | ✅ (should have been posted) |
| `duplicate` | ✅ (sibling) | ❌ (redundant) |
| `severity_mismatch` | ✅ | ⚠️ wrong severity |
| `category_mismatch` | ✅ | ⚠️ wrong category |
| `actionable_but_weak` | ✅ (minor) | ❌ (too noisy) |
| `correct_but_not_worth_posting` | ✅ (observation) | ❌ (no action needed) |

### Metric targets summary

| Metric | Formula | Target |
|---|---|---|
| Precision | TP / (TP + FP) | ≥ 0.75 |
| Recall | TP / (TP + FN) | ≥ 0.60 (high/critical) |
| Clean-case FP rate | Clean FP cases / Clean cases | ≤ 0.10 |
| Anchor validity | Anchored findings / Total findings | ≥ 0.95 |
| Schema validity | Valid findings / Raw findings | ≥ 0.99 |
| Cost per useful finding | Cost USD / (Applied + Ack) | ≤ $0.15 (Sonnet) |
| Useful rate | (Applied + Ack) / Classified | ≥ 0.35 |
| Dismiss rate | Dismissed / Classified | ≤ 0.20 |
| Ignore rate | Ignored / Classified | ≤ 0.35 |
