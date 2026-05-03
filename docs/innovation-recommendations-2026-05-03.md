# Nash AI — Innovation Recommendations Report

**Session:** 2026-05-03 | **Papers synthesized:** 78 across 4 domains  
**Domains:** Code Quality & Review · Prompt Evaluation · Efficiency · Prompt Injection & Security

---

## Discussion Synthesis

Across all four research domains, a single meta-pattern dominates: **single-pass, single-model inference is uniformly the weakest configuration**. The code quality literature (APR, hallucination taxonomy, agentic SE survey) shows that iterative feedback loops—where static analysis, test execution, or a critic agent validates and challenges the first output—substantially outperform one-shot generation. The prompt evaluation literature independently arrives at the same conclusion: multi-agent judge pipelines achieve 83–99% expert agreement while single-agent evaluators remain fragile to prompt formulation and score-distribution bias. Efficiency research does not contradict this; it provides the infrastructure to make multi-pass cheaper through speculative decoding, KV cache reuse, and context compression. The implication for Nash AI is structural: the current ReAct loop produces a single review pass with LLM-only validation. Adding a lightweight critic pass with tool-verified evidence gates, an auto-rubric evaluator scoring findings before posting, and prefix-cached prompt reuse would transform the architecture from a "generate-and-post" system into a "generate–evaluate–filter–post" pipeline, matching the approach that consistently wins in every domain studied.

A second convergent theme is **untrusted content as a first-class threat model**. Nash AI's core exposure surface — PR diffs written by external contributors — is exactly the attack surface that the injection research considers most dangerous. Three independent papers on indirect prompt injection in agentic systems (including one specifically targeting AI peer reviewers) report 40–86% manipulation success rates, with position bias making early-in-diff payloads disproportionately dangerous. Combined with hidden-comment injection through code comments and the systematic taxonomy of injection threats across 17 papers, it is clear that the current "diff is untrusted" note in the system prompt is necessary but not sufficient. Architectural controls — semantic instruction-deviation detection, content-vs-system-prompt separation, and adversarial testing via automated red-teaming — are required to harden a production agent that reads arbitrary code from the internet.

---

## Ranked Innovation Recommendations

---

### #1 — Critic Agent Validation Gate

**Impact:** HIGH  
A critic agent that challenges each finding before it is posted directly targets Nash AI's most costly failure mode: false positives that produce `dismissed` and `ignored` outcomes. The Eco-Evolve architecture reports a 26.6-point improvement over single-agent baselines on SWE-bench; TRACE-ED's multi-agent grading framework achieves substantially better grounding than single-agent; the iterative test+static-analysis loop paper demonstrates that each additional feedback cycle narrows the FP set. For Nash AI, precision is gated at ≥0.75 with an alert below 0.65 — a critic pass is the most direct way to shrink the FP count without sacrificing recall.

**Innovation:** Nash AI already has a multi-stage pipeline (fast-path → main review → editor). The critic would run as a new stage between raw finding generation and the editor, reusing the existing `ReviewModelAudit` audit row contract. No new database tables needed; a new `stage = "critic"` value extends the existing enum. The critic is prompted with the finding, the diff context, and tool-call evidence, then asked to assign a challenge score and rebut if warranted — this is directly the "self-evolution" mechanism from Eco-Evolve.

**Papers:** 10.20944/preprints202603.0129.v1, 10.21203/rs.3.rs-8985839/v1, 10.1007/s44163-026-01009-5, 10.1145/3796507, 10.2196/75932

**Implementation sketch:** Add a `CriticStage` class in `apps/api/src/app/agent/` that accepts a list of `Finding` objects from the main review stage and runs a second LLM call per finding (or batched) with a structured critic prompt. The critic returns a `CriticVerdict` Pydantic model: `{finding_id, upheld: bool, challenge: str | None, confidence_delta: int}`. The editor stage then gates on `upheld=True` or adjusts `confidence` by `confidence_delta` before deciding whether to post. To control cost, only apply the critic to findings with `confidence < 80` or `evidence = "inference"` — the cases where FPs concentrate.

**Difficulty:** MEDIUM — new LLM call per finding batch; existing pipeline stages provide clean insertion points.

---

### #2 — Auto-Rubric Evaluation for Prompt Versioning

**Impact:** HIGH  
Nash AI already has a quality model with precision/recall/FP-rate targets and an eval pipeline in `evals/`. The gap is the evaluator itself: `evals/metrics.py` uses exact-match heuristics against `expected.json`. LLM-as-Judge benchmarks show Claude Sonnet achieving 99.79% GJAR in structured rubric-based judgment; Autorubric generates unified task-specific rubrics automatically; TRACE-ED's 5-dimension transparency framework maps directly onto Nash AI's existing label taxonomy. Replacing or augmenting the heuristic matcher with an LLM judge that applies Nash's rubric would give a continuous quality signal for every prompt version change, not just the cases where `expected.json` has ground truth.

**Innovation:** Nash AI's quality model already defines the rubric dimensions. The auto-rubric approach means the LLM judge is given the rubric text as context and scores each finding across the five existing label dimensions. This turns the existing label taxonomy into a zero-shot evaluation protocol with no additional annotation required — novel for a code review system.

**Papers:** 10.48550/arxiv.2603.00077, 10.3390/electronics15030659, 10.21203/rs.3.rs-8985839/v1, 10.48550/arxiv.2602.08672, 10.30537/sjcms.v9i02.1776, 10.2196/75932

**Implementation sketch:** Create `evals/llm_judge.py` that reads a `Finding` and its diff context, then calls Claude with Nash's quality rubric to produce a structured judgment matching the `BenchmarkResult` schema. Integrate into `evals/run_eval.py` as an optional `--judge-mode llm` flag. The judge output supplements (not replaces) the heuristic matcher for cases where no `expected.json` entry exists. Store judge results in a new `BenchmarkJudgment` table alongside `BenchmarkResult`. Gate prompt version merges when LLM judge precision drops more than 5 pp from the prior version.

**Difficulty:** LOW — purely in the eval pipeline; no production path changes.

---

### #3 — Semantic Instruction-Deviation Detector for Indirect Injection

**Impact:** HIGH  
The threat is concrete and specific to Nash AI's architecture: PR diffs written by external contributors are parsed and fed into the agent context. Three papers on indirect injection in agentic systems, including one targeting AI peer reviewers specifically, report 40–86% manipulation success with position-sensitive payloads (early-in-diff payloads are more dangerous). The embedding-based IPIA detector achieves F1=0.977 at 0.001ms inference — fast enough to run inline without violating the <10s webhook budget.

**Innovation:** Rather than keyword filtering, the embedding-distance approach measures whether the agent's next tool call or output deviates semantically from what the system prompt authorizes. Applied to Nash AI's ReAct loop, the detector runs after each `Thought:` step and flags any instruction that originated from diff content rather than the system prompt.

**Papers:** 10.3390/a19010092, 10.62411/jcta.15254, 10.21203/rs.3.rs-8432945/v1, 10.48550/arxiv.2602.10498, 10.1145/3800948, 10.48550/arxiv.2602.10453, 10.5281/zenodo.18729244

**Implementation sketch:** Add an `InjectionDetector` class in `apps/api/src/app/agent/security.py`. Use embeddings to compute cosine distance between each agent `Thought` step and the system prompt's authorized scope embedding. Flag and sanitize when distance exceeds a calibrated threshold (start at 0.4). Wire into the ReAct loop in `apps/api/src/app/agent/runner.py` after each thought step. Log injection attempts at `WARN` level including the content hash. Additionally, add a pre-processing sanitizer that strips HTML comments and zero-width characters from diff lines before they enter the agent context.

**Difficulty:** MEDIUM — new dependency (`sentence-transformers` or API call); requires ReAct loop modification and threshold calibration.

---

### #4 — Iterative Static Analysis Feedback Loop

**Impact:** HIGH  
The iterative test+static-analysis loop paper shows that running static analysis, providing findings back to the LLM, then re-analyzing substantially outperforms single-pass review. Chain-of-thought reasoning substantially reduces false positive rates in an industry setting. Nash AI already has a `tool_verified` evidence tier — the missing piece is a structured "challenge-with-evidence" loop where static analysis output feeds back into the agent's reasoning before findings are finalized.

**Innovation:** Currently the Nash AI ReAct loop runs tools reactively. The innovation is a proactive multi-pass: (1) initial analysis, (2) static analysis tools automatically invoked on all flagged file paths, (3) output feeds back as a second reasoning pass. This mirrors the neuro-symbolic MemHint approach (Z3-backed symbolic reasoning as a second pass).

**Papers:** 10.1007/s44163-026-01009-5, 10.48550/arxiv.2601.18844, 10.48550/arxiv.2603.27224, 10.1145/3799693, 10.1007/s10664-026-10802-w

**Implementation sketch:** After the first ReAct pass completes, collect all `Finding.file_path` values. Run `ruff`/`semgrep` via existing tool infrastructure against those files and diff lines. Inject results as a new observation: "Static analysis found the following. Reconsider your findings in light of this evidence." Allow one additional reasoning step before finalizing. Cap extra step at `max_tokens_additional = 1000` to bound cost.

**Difficulty:** MEDIUM — requires modifications to `runner.py` loop termination logic and a new static analysis tool wrapper.

---

### #5 — Agentic RAG for Vulnerability Knowledge Retrieval

**Impact:** HIGH  
Vul-RAG achieves 16–24% accuracy improvement and found 10 previously unknown Linux kernel bugs using knowledge-level RAG. Nash AI's current agent relies entirely on Claude's pretraining, which the hallucination taxonomy paper shows misses 40–60% of hallucination-class bugs including phantom API references.

**Innovation:** An agentic RAG tool lets the agent query a curated CVE/vulnerability-pattern store on-demand during the ReAct loop. The agent retrieves semantically similar known vulnerabilities as evidence, directly improving `evidence` tier classification and reducing `inference`-grade findings.

**Papers:** 10.1145/3797277, 10.3390/electronics15030612, 10.7717/peerj-cs.3642, 10.3390/app16010517, 10.1109/tse.2026.3657432

**Implementation sketch:** Create a `VulnerabilityKnowledgeBase` class in `apps/api/src/app/agent/tools/vuln_rag.py`. Populate from NVD/CVE data and existing `evals/datasets/` ground truth. Use pgvector in the existing Postgres instance — no new infrastructure. Register a new ReAct tool `search_vulnerability_patterns(code_snippet: str, category: str) -> list[VulnMatch]` with max 3 results per call. The agent uses this when `category = "security"` and evidence would otherwise be `"inference"`.

**Difficulty:** MEDIUM — requires pgvector extension and one-time CVE import script; no new infrastructure.

---

### #6 — Prompt Prefix Caching for Cost Reduction

**Impact:** MEDIUM  
Prefix caching achieves 40–70% cache hit rates for repeated system-prompt prefixes. Nash AI's system prompt is large and identical across all reviews of the same `(model, prompt_version)` pair. Attn-GS context compression reports 60–70% context reduction for diff-content while preserving accuracy — directly applicable to large diffs.

**Innovation:** Refactoring Nash AI's prompt construction to maximize stable prefix length, combined with Anthropic's prompt caching API, reduces both latency and cost without model changes.

**Papers:** 10.52710/cfs.888, 10.36227/techrxiv.176046306.66521015/v3, 10.48550/arxiv.2602.07778, 10.48550/arxiv.2601.10729

**Implementation sketch:** Restructure prompt templates so all static content (rules, schema, examples) is in one contiguous prefix block before variable content (diff, PR metadata). Add `cache_control: {"type": "ephemeral"}` markers on the static prefix when calling Claude. For PRs with diffs > 4000 tokens, pre-process by truncating unchanged context lines to ±2 lines per hunk and summarizing unchanged files above 200 lines to their signature only. Track cache hit rates via `ReviewModelAudit` JSONB metadata.

**Difficulty:** LOW — prompt restructuring and SDK parameter change; no architectural changes.

---

### #7 — CoT Reusability and Verifiability Scoring

**Impact:** MEDIUM  
CoT evaluation papers show reasoning chains can be scored for structural coherence, logical consistency, and verifiability, and that low-scoring chains correlate with false positives. For Nash AI, the agent's `Thought:` steps are not just ephemeral scaffolding; they are a quality signal.

**Innovation:** Nash AI currently discards the agent's intermediate reasoning after extracting `Finding` objects. Scoring the reasoning chain before accepting findings means findings with incoherent supporting chains get their `confidence` capped, preventing them from reaching `critical` severity.

**Papers:** 10.48550/arxiv.2602.17544, 10.3390/ai7010035, 10.48550/arxiv.2602.06098

**Implementation sketch:** Capture the full `(thought, action, observation)` triple list for each finding. After the ReAct loop, pass to a `CoTScorer.score(chain: list[ReActStep]) -> CoTScore` function that checks: (1) at least one tool-verified observation anchors the chain, (2) the final thought cites the observation, (3) no logical reversal between thought and finding. If `CoTScore.coherent = False`, downgrade `Finding.confidence` by 20 and set `evidence = "inference"`. Add `cot_score` to `ReviewModelAudit` JSONB metadata.

**Difficulty:** LOW — implemented entirely within the existing agent runner; no external calls or schema changes.

---

### #8 — PR Effort Prediction for Fast-Path Routing

**Impact:** MEDIUM  
Diff metadata features (changed files, lines added/deleted, file types, hunk count) can predict review effort before any LLM call. Nash AI already has a fast-path routing stage; adding effort-prediction features would improve `light_review` vs `full_review` decisions, reducing unnecessary full-review runs on simple formatting or documentation PRs.

**Innovation:** The current fast-path relies primarily on LLM confidence and file-class heuristics. Structural metadata features provide a complementary signal requiring no LLM call — making the router more robust to `missing_confidence` events.

**Papers:** 10.48550/arxiv.2601.00753, 10.21203/rs.3.rs-8732393/v1

**Implementation sketch:** Compute a `DiffComplexityFeatures` struct from the parsed diff: `(file_count, hunk_count, added_lines, deleted_lines, file_type_histogram, has_test_only_changes, has_doc_only_changes, touched_sensitive_paths)`. Train a lightweight logistic regression offline on historical `ReviewModelAudit` data to predict `review_effort: light | full | high_risk`. Wire prediction into fast-path decision logic in `apps/api/src/app/agent/fast_path.py` as a tie-breaker when LLM confidence is missing. Serialize as a small pickle loaded at worker startup.

**Difficulty:** LOW — structural feature extraction is deterministic; ML model is offline-trained.

---

### #9 — Multi-Dimensional Finding Quality Evaluation at Post-Time

**Impact:** MEDIUM  
Multi-label code smell and multi-dimensional quality evaluation research demonstrates that single-dimension quality assessment systematically misclassifies findings that are correct on one axis but problematic on another. Nash AI's label taxonomy already captures multi-dimensional structure, but the finding schema enforces only one `category` and one `severity`.

**Innovation:** A multi-label soft-scoring model at post-time checks each finding against five risk axes simultaneously: correctness risk, security risk, actionability risk, duplication risk, and severity calibration risk — enabling finer routing (downgrade severity rather than drop; merge near-duplicates rather than post both).

**Papers:** 10.1109/access.2025.3648907, 10.1145/3800582, 10.1109/tse.2026.3657432, 10.33395/sinkron.v10i1.15439

**Implementation sketch:** Extend the editor stage in `apps/api/src/app/agent/editor.py` to compute a `QualityVector` for each finding: a 5-dimensional float vector from a lightweight classifier. Thresholds per dimension control routing: low correctness → drop; low severity calibration → downgrade one level; high duplication → merge with similar finding in the batch. Extend `DropReason` enum in `apps/api/src/app/agent/schema.py` with `severity_downgraded` and `merged_duplicate`.

**Difficulty:** MEDIUM — requires extending the editor stage and the `DropReason` enum; moderate test surface.

---

### #10 — Adversarial Red-Teaming Infrastructure for Injection Hardening

**Impact:** MEDIUM  
Nash AI has no automated adversarial test suite for injection resilience. The agentic LLM trust poisoning paper reports 40.6% failure rate and 72.7% position-bias exploitability. Given that Nash AI is a production agent reading untrusted code, a regression test suite of adversarial diffs is essential.

**Innovation:** A PromptFuzz-style automated generator creates adversarial diff payloads covering the known injection taxonomy (direct instruction injection in comments, zero-width character hiding, multi-step context poisoning, position-sensitive early-payload attacks) and runs them against the Nash agent — creating a living adversarial regression suite.

**Papers:** 10.1109/tifs.2026.3666893, 10.1109/tdsc.2026.3665230, 10.21203/rs.3.rs-8872967/v1, 10.48550/arxiv.2602.10453, 10.5281/zenodo.18137846, 10.1371/journal.pone.0338083

**Implementation sketch:** Create `evals/adversarial/` with a generator script (`gen_injection_cases.py`) producing diff payloads for each injection category. Add an `adversarial` pytest marker that runs the Nash agent against these payloads and asserts: (1) no finding category is `injected_instruction`, (2) tool calls remain within authorized set, (3) no finding cites injected comment content as evidence. Populate with 20 hand-crafted cases covering 5 injection vectors (code comment, docstring, variable-name, multi-line string, config file injection). Wire into CI as a nightly job.

**Difficulty:** HIGH — requires building test infrastructure from scratch; high value but not incremental.

---

## Implementation Priority Summary

| Rank | Recommendation | Impact | Difficulty | Quick Win? |
|------|---------------|--------|------------|------------|
| 1 | Critic Agent Validation Gate | HIGH | MEDIUM | No |
| 2 | Auto-Rubric Evaluation for Prompt Versioning | HIGH | LOW | **Yes** |
| 3 | Semantic Instruction-Deviation Detector | HIGH | MEDIUM | No |
| 4 | Iterative Static Analysis Feedback Loop | HIGH | MEDIUM | No |
| 5 | Agentic RAG for Vulnerability Knowledge | HIGH | MEDIUM | No |
| 6 | Prompt Prefix Caching for Cost Reduction | MEDIUM | LOW | **Yes** |
| 7 | CoT Reusability and Verifiability Scoring | MEDIUM | LOW | **Yes** |
| 8 | PR Effort Prediction for Fast-Path Routing | MEDIUM | LOW | **Yes** |
| 9 | Multi-Dimensional Finding Quality Evaluation | MEDIUM | MEDIUM | No |
| 10 | Adversarial Red-Teaming Infrastructure | MEDIUM | HIGH | No |

**Recommended first sprint:** Items #2, #6, #7, #8 are all LOW difficulty and can be parallelized. Combined they address cost reduction, eval pipeline quality, and fast-path reliability without touching the production agent loop. Items #1 and #3 are the highest-leverage architectural changes and should be the second sprint.
