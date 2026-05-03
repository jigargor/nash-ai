# Nash AI Innovation Recommendations — 2026-05-03 (Run 2)

**Research session:** 2026-05-03 daily cron  
**Papers reviewed this session:** 32 new papers (across 3 specialist agents)  
**Multi-agent discussion:** 3 innovation agents (Security, Quality/Eval, Architecture)  
**Orchestration model:** Sonnet 4.6  

---

## Top Innovations — Ranked (Impact ↓, Innovation ↓, Difficulty ↑)

| # | Title | Impact | Difficulty | Grounding DOIs |
|---|-------|--------|------------|----------------|
| 1 | Trajectory-Locked Review Contract | HIGH | MEDIUM | 2510.11851, 2510.09462, 2510.23883 |
| 2 | LCEF-Style Two-Stage Review Routing | HIGH | MEDIUM | 2511.00215 |
| 3 | Weekly Bradley–Terry Human Calibration | HIGH | MEDIUM | pone.0339920, 2510.24891 |
| 4 | Claim–Evidence Consistency Gate (VeriCoT) | HIGH | MEDIUM | 2511.04662 |
| 5 | Verifier-Gated Security Comments (AdaTaint) | HIGH | HIGH | 2511.04023, 3720488 |
| 6 | Cohesion Drift Pre-Screen on Hunks | HIGH | LOW-MED | 2510.14778 |
| 7 | Blame-Anchored Evidence Bundles | MEDIUM | LOW | 2511.01047 |
| 8 | Slice-Native Regression Harness | MEDIUM-HIGH | MEDIUM | 2511.00619, 2510.18560 |
| 9 | PR Edit-Surface Map Prepass | MEDIUM | MEDIUM | 2511.11012 |
| 10 | KV Policy as Compliance Control | MEDIUM | LOW-MED | 2510.00231, 2510.01290 |

---

## Detailed Innovation Cards

### 1. Trajectory-Locked Review Contract
**Impact: HIGH | Difficulty: MEDIUM**  
**Grounded in:** `10.48550/arxiv.2510.11851`, `10.48550/arxiv.2510.09462`, `10.48550/arxiv.2510.23883`, `10.18653/v1/2025.findings-naacl.395`

Treat each review job as a signed, immutable **ReviewContract**: allowed GitHub operations, max tool rounds, file/path allowlist derived from webhook scope, severity rubric version, banned actions (edit workflow files, request new scopes, post on non-diff lines). After every tool observation, run a **cheap deterministic reconciler** (not another LLM monitor) that checks:
- Next planned tool + JSON args are within contract
- Observations don't expand scope to new repos/branches/privileged paths
- Suggestion blocks only touch paths in the parsed diff

If reconciliation fails → halt posting + emit bounded incident record.

**Why novel**: Many agents add "a safety model"; deep research shows that is insufficient under adaptive attacks. Nash's attack surface is exactly long-horizon tool use with adversarial PR text — trajectory binding creates control-plane/data-plane separation.

---

### 2. LCEF-Style Two-Stage Review Routing
**Impact: HIGH | Difficulty: MEDIUM**  
**Grounded in:** `10.48550/arxiv.2511.00215` (DocPrism — cuts FP 98% → 14%, accuracy 14% → 94%)

Stage A: Fast local categorizers per hunk (rule tags + tiny classifier):  
`security-sink-candidate`, `authz-boundary`, `migration`, `secrets`, `pure-style`

Stage B: External filters before any GitHub API write:
- Required tool receipts (linter/rule pack)
- Dependency allowlists
- Path-sensitive policies (matching existing `81-path-aware-review-strictness`)
- Evidence schema gate

Only hunks passing filters receive full ReAct deep-dive; others are dropped or downgraded to summary-level notes.

**Why novel**: Allocates compute explicitly and cuts the high-FP tail by separating cheap local labeling from expensive LLM judgment.

---

### 3. Weekly Bradley–Terry Human Calibration for LLM-as-Judge
**Impact: HIGH | Difficulty: MEDIUM**  
**Grounded in:** `10.1371/journal.pone.0339920` (τ ≈ 0.59-0.68 with calibrated judge), `10.48550/arxiv.2510.24891` (JudgeEval harness)

Sample weekly panel of real PR findings (or synthetic pairs by repo/language). Engineers rate blinded pairs ("which comment is more correct / more actionable / better severity?"). Fit Bradley-Terry model on pairwise outcomes; calibrate:
- Severity thresholds per tier
- Judge rubric weights
- Drift alerts when τ drops week-over-week

JudgeEval-style rubric-grounded criteria become annotation schema: correctness, evidence grounding, severity appropriateness, actionability.

**Why novel**: Turns Nash into a closed-loop measurement system where the LLM reviewer is treated as a scorer that must stay aligned to humans on concrete axes—not a one-shot judge.

---

### 4. Claim–Evidence Consistency Gate (VeriCoT Pattern)
**Impact: HIGH | Difficulty: MEDIUM**  
**Grounded in:** `10.48550/arxiv.2511.04662` (neuro-symbolic CoT validation via logical consistency checks)

After ReAct loop proposes a finding, run a second structured pass:
1. Extract atomic claims ("X is vulnerable because Y", "this breaks API Z")
2. Map each claim to cited diff hunks / file paths / tool observations
3. Apply lightweight consistency rules:
   - No claim about a line not in the cited hunk
   - No CWE label unless matched pattern
   - Severity must track with evidence strength

Failures **block or downgrade** the finding → route to "needs human/triage" bucket instead of posting. No full FOL theorem proving needed in v1—constraint checking is sufficient.

**Why novel**: Untrusted diffs create ungrounded nits and hallucinated severity. Nash's product promise is inline, line-specific comments — this gates publication on logical glue between claim and evidence.

---

### 5. Verifier-Gated Security Comments: LLM Hypothesizes, Analyzer Proves
**Impact: HIGH | Difficulty: HIGH**  
**Grounded in:** `10.48550/arxiv.2511.04023` (AdaTaint — 43.7% FP reduction), `10.1145/3720488` (Artemis SSRF — 207 true paths vs 15 FPs)

For `security-*` categories from Stage A, agent emits a **structured hypothesis**:
```json
{
  "source": "file:line",
  "sink": "file:line",  
  "sanitizer": null,
  "caller_edges": ["..."],
  "file_line_anchors": ["..."]
}
```
Nash runs a bounded static proof pass (CodeQL query pack, tree-sitter reachability slice, scoped to changed files + N-hop imports). Inline comment posted **only if** analyzer returns confirming witness (path ID, query name, "reachable" proof object) attached as audit metadata. Conflicts downgrade to questions or are suppressed.

**Why novel**: Nash already treats diffs as untrusted; this adds "untrusted-LLM, trusted-proof" for highest-risk claims. Wrong critical security comments erode trust and enable manipulation.

---

### 6. Cohesion Drift Pre-Screen on Changed Hunks
**Impact: HIGH | Difficulty: LOW-MEDIUM**  
**Grounded in:** `10.48550/arxiv.2510.14778` (code cohesion drops under malicious grafts)

For each diff hunk, compute **repo-relative cohesion features**:
- Import graph consistency
- Identifier style continuity  
- Symbol neighborhood agreement (same-module naming patterns)
- "Unexpected sink" proximity (network/process/crypto calls)

Flag high-drift hunks before the LLM deep-reads them:
- Route to stricter tool constraints (no broad file fetch beyond hunk without contract update)
- Mandatory dual-evidence posting rules (finding must cite both AST/diff span + deterministic signal)

**Why novel**: Not "another static analyzer loop." This is a **structural anomaly gate** tuned for small malicious grafts and weird drive-by edits — catches supply-chain style attacks before or alongside LLM reasoning.

---

### 7. Blame-Anchored Evidence Bundles (Lightweight History)
**Impact: MEDIUM | Difficulty: LOW**  
**Grounded in:** `10.48550/arxiv.2511.01047` (HAFixAgent — +212% over snapshot-only agents)

For each changed region, fetch **minimal git blame** (last author/date/SHA, not full history) and attach as fixed JSON field to agent context. Use only to disambiguate intent vs. accident ("this line predates the PR," "touched but not authored here") and steer questions. Never use blame as authority — only as **localization prior**.

**Why novel**: Nash is single-pass today. Blame is a surgical, token-cheap partial answer to "why does this line exist?" reducing context-free invented rationale without building a general history-aware reviewer.

---

### 8. Slice-Native Regression Harness
**Impact: MEDIUM-HIGH | Difficulty: MEDIUM**  
**Grounded in:** `10.48550/arxiv.2511.00619` (GDPR-Bench multi-granularity), `10.48550/arxiv.2510.18560` (WebDevJudge rubrics)

Versioned benchmark pack: synthetic + curated real anonymized snippets with gold labels at multiple granularities (security / compliance / style). Each item has structured rubric dimensions (WebDevJudge-style query-grounded rubrics). CI outputs dashboards: F1 by slice, functional check gaps, bias indicators (language/framework skew). Release gates tied to **slice floors**, not a single average score.

**Why novel**: Without automated eval, Nash optimizes vibes. Makes FPs and blind spots measurable per product-critical slice before reaching customers.

---

### 9. PR Edit-Surface Map Prepass (Multi-Hunk Localization Graph)
**Impact: MEDIUM | Difficulty: MEDIUM**  
**Grounded in:** `10.48550/arxiv.2511.11012` (Beyond Accuracy: multi-hunk failures cost 39-343% more tokens)

Before main ReAct loop, build a compact map of hunks:
- File adjacency
- Shared symbol references (imports, types, calls)
- "Must review together" clusters

Planner's first tool calls target **clusters**, not files in arbitrary order — reducing missed cross-hunk inconsistencies and avoiding redundant re-reads.

**Why novel**: Inline review quality is limited by fragmented attention across related edits. An explicit map operationalizes repo-level localization for *review*, not patch generation.

---

### 10. KV Policy as Compliance-Preserving Control
**Impact: MEDIUM | Difficulty: LOW-MEDIUM**  
**Grounded in:** `10.48550/arxiv.2510.00231` (KV pitfalls — eviction drops security rules silently), `10.48550/arxiv.2510.01290` (ThinKV — thought-adaptive retention)

Treat "policy + rubric + severity contract" as non-evictable state (or re-inject between tool rounds). Order prompts so protective constraints are structurally hard to truncate. Use thought-adaptive KV budgets for long CoT reasoning segments.

Key insight: eviction policy is a compliance risk, not just a latency knob. Long reviews with tool-fetched files can silently drop `UNTRUSTED_CONTENT` and severity rules.

---

## Cross-Agent Discussion Insights

### Security → Quality Connection
The context-robustness / flip phenomenon studied for RAG safety (benign context flipping guardrails 8-15% of the time) is isomorphic to a code review **quality** failure mode: benign surrounding context causes the model to stabilize the wrong mental model (false confidence, wrong root cause). Nash can borrow this empirical mindset: treat flips under benign context perturbations as a **review quality reliability signal**, especially for nits-vs-bug classification on large PRs.

### Architecture → Review Quality Connection
TDFlow's sub-agent decomposition (Propose → Debug → Revise → Verify) maps cleanly to review comment quality: **Propose** candidate findings → **Debug** via tools (fetch related symbols, scoped checks) → **Revise** severity under structured template → **Verify** with small reranker + security process scoring (SecCodePRM). This maps repair-agent decomposition to comment quality and process hygiene.

### Eval → Architecture Connection
SCoT (Structured Chain-of-Thought) finding: forcing sequential/branch/loop reasoning structure before output yields large gains. For Nash: elicit structured review planning (hypothesis → evidence chain → severity reasoning) before emitting inline findings — improves citation-to-line discipline and severity calibration.

---

## New Papers This Session (32 papers, 4 categories)

### Code Quality & Static Analysis (11 papers)
- 10.48550/arxiv.2510.10290 — Grounded AI for Code Review (AST+static, enterprise)
- 10.48550/arxiv.2511.00215 — DocPrism LCEF (FP 98%→14%, accuracy 14%→94%)
- 10.48550/arxiv.2511.04179 — Explaining Software Vulns with LLMs (SAFE IDE plugin)
- 10.48550/arxiv.2511.04023 — AdaTaint (LLM-proposed sources/sinks + neuro-symbolic, -43.7% FP)
- 10.1145/3720488 — Artemis SSRF (hybrid taint + LLM, 207 paths vs 15 FPs)
- 10.4204/eptcs.427.7 — Solidity Defect Validation (Slither + LLM + sym exec)
- 10.48550/arxiv.2510.23068 — Checkstyle+ (lint + LLM semantic nuance)
- 10.48550/arxiv.2511.01047 — HAFixAgent (+212% over snapshot agents with blame context)
- 10.48550/arxiv.2510.23761 — TDFlow (sub-agent decomposition, SWE-Bench Lite)
- 10.48550/arxiv.2511.11012 — Beyond Accuracy: Agentic Multi-Hunk Repair
- 10.48550/arxiv.2511.00619 — GDPR-Bench-Android (multi-granularity benchmark)

### Prompt Eval, Efficiency & Reasoning (11 papers)
- 10.1371/journal.pone.0339920 — Human-anchored Bradley-Terry LLM judge calibration
- 10.48550/arxiv.2510.24891 — Idea2Plan / JudgeEval (rubric-grounded judge evaluation)
- 10.48550/arxiv.2510.18560 — WebDevJudge (structured rubric benchmark, LLM-vs-expert gap)
- 10.48550/arxiv.2511.11733 — Speculative Decoding Decentralized (~2.57× speedup)
- 10.48550/arxiv.2510.00231 — Pitfalls of KV Cache Compression (multi-instruction dropping)
- 10.48550/arxiv.2510.01290 — ThinKV (thought-adaptive KV, near-lossless)
- 10.1145/3690635 — Structured CoT (SCoT) for code generation
- 10.48550/arxiv.2511.04662 — VeriCoT (neuro-symbolic CoT logical consistency checks)
- 10.48550/arxiv.2510.23083 — Small Process/Outcome Critics (>20% best-of-N gain)
- 10.48550/arxiv.2602.10418 — SecCodePRM (security process reward model)
- 10.48550/arxiv.2511.01043 — DPO-F+ (preference alignment for repair feedback)

### Injection & Adversarial Security (10 papers)
- 10.18653/v1/2025.findings-naacl.395 — Adaptive Attacks Break Defenses (NAACL 2025)
- 10.48550/arxiv.2510.06445 — Survey on Agentic Security (150+ paper taxonomy)
- 10.48550/arxiv.2510.23883 — Agentic AI Security survey (MCP/A2A, multi-agent propagation)
- 10.1145/3696410.3714756 — RAGForensics (poisoning traceback for RAG corpora)
- 10.48550/arxiv.2510.14778 — Code Cohesion for Supply Chain Attacks
- 10.48550/arxiv.2511.16709 — AutoBackdoor (peer review manipulation, >90% ASR)
- 10.48550/arxiv.2510.05310 — RAG Makes Guardrails Unsafe (8-15% flip rate)
- 10.48550/arxiv.2510.09462 — Adaptive Attacks on Trusted Monitors
- 10.48550/arxiv.2510.01359 — Breaking the Code: Jailbreaking Code Agents
- 10.48550/arxiv.2510.11851 — Deep Research Brings Deeper Harm (trajectory hijack)

---

## Session Metadata
- Total papers seen across all sessions: ~210
- This session new DOIs: 32
- Recommendations this session: 10
- R2 manifest: saved to `llm-research/manifests/2026-05-03-run2.json`
