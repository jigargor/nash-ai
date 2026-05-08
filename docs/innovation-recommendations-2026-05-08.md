# Nash AI — LLM Research Innovation Report
**Date**: 2026-05-08  
**Session**: Daily cron  
**Papers Reviewed**: 28 new (deduplicated against 300+ previously seen)  
**Recommendations Generated**: 12  
**Orchestration Model**: Sonnet 4.6 (cloud agent)  
**Research Lenses**: Security/Injection, Efficiency/MoE, Code Quality/Eval  

> **Note on subagent models**: User-requested models (GPT 5.5 Medium, Opus 4.7 High, Opus 4.6 High) are not available as Task subagent slugs in this environment. Research lenses were executed with `composer-2-fast`. Inform user to update available model roster via Cursor Cloud settings.  
> **Artiforge**: Still in ERROR state — unavailable for agent orchestration.  
> **Zotero**: API key invalid (403). Credential regeneration needed at https://www.zotero.org/settings/keys.

---

## New Papers Reviewed Today

### Code Quality & Review
| DOI | Title | Relevance |
|-----|-------|-----------|
| 10.1145/3626252.3630773 | Real-Time Style Feedback (RTSF) — CS1 5x engagement via real-time LLM | Fine-grained actionability metrics |
| 10.48550/arxiv.2510.24358 | PRDBench: Agent-Driven Benchmark Construction | Living benchmarks for agent eval |
| 10.48550/arxiv.2510.06186 | RECODE-H: Interactive Human Feedback Benchmark | Multi-turn eval for code agents |
| 10.48550/arxiv.2510.19296 | QiMeng-SALV: Signal-Aware DPO for Verilog | Granular partial-correctness signals |
| 10.48550/arxiv.2510.02341 | DRIFT: Dissatisfaction-Refined Iterative Preference Training | Real-world DSAT signal learning |

### Prompt Evaluation & Judges
| DOI | Title | Relevance |
|-----|-------|-----------|
| 10.48550/arxiv.2510.06538 | APE: Auto-Prompt Ensemble for LLM Judges | Failure-mined evaluation dimensions |
| 10.48550/arxiv.2510.04633 | Topic-Specific Classifiers > Prompted LLM Judges | Domain-specific judging superiority |
| 10.48550/arxiv.2510.26852 | CATArena: Tournament-Style LLM Agent Eval | Score-saturation-aware eval design |
| 10.48550/arxiv.2511.10049 | Continuous Benchmark Generation (Enterprise) | Living benchmarks as code |
| 10.48550/arxiv.2510.21524 | EU-Agent-Bench: Illegal Behavior of LLM Agents | Legal-compliance safety eval |
| 10.18653/v1/2023.findings-emnlp.946 | TELeR: Taxonomy of LLM Prompts | Prompt complexity classification |
| 10.3389/fdata.2025.1611389 | LLM-as-a-Judge for Search Query Parsing | Contextual eval prompt routing |
| 10.1145/3705328.3759305 | Profile-Aware LLM-as-a-Judge for Recommendations | Profile-contextualized judgment |

### Efficiency & MoE
| DOI | Title | Relevance |
|-----|-------|-----------|
| 10.48550/arxiv.2510.10302 | SP-MoE: Speculative Expert Prefetching | Structural prefetch for tool chains |
| 10.48550/arxiv.2511.14102 | MoE-SpeQ: Speculative Quantized Decoding + Expert Prefetch | Adaptive speculation + roofline model |
| 10.48550/arxiv.2511.10054 | BuddyMoE: Expert Redundancy for Prefetch Misses | Fallback asset substitution |
| 10.48550/arxiv.2511.10676 | Pre-Attention Expert Prediction (93-97% accuracy) | Cheap early routing signals |
| 10.48550/arxiv.2510.26730 | ExpertFlow: Adaptive Expert Scheduling | Runtime-adaptive prefetch horizon |
| 10.48550/arxiv.2510.05781 | MoNE: Mixture of Neuron Experts (50% activation) | Neuron-granular sparse activation |
| 10.48550/arxiv.2510.22852 | E2D2: Encoder-Decoder Diffusion LMs | Context split: stable encode / iterative decode |
| 10.48550/arxiv.2510.02358 | DiffuSpec: Diffusion LMs for Speculative Decoding | Bidirectional drafting + causal-consistency search |
| 10.48550/arxiv.2510.00294 | FreeDave: Lossless Parallel Decoding for DLLMs | 3.78x speedup, no degradation |
| 10.1117/12.3061241 | CPU-GPU Collaborative Speculative Inference | CPU underutilization recovery |
| 10.3390/electronics13071376 | Hybrid Model Branch Prediction for Inference | 3.4x speedup via binomial predictor |
| 10.48550/arxiv.2510.26622 | Encoder-Decoder vs Decoder-Only LLM Revisited | Inference efficiency parity + gains |

### Security & Injection
| DOI | Title | Relevance |
|-----|-------|-----------|
| 10.48550/arxiv.2510.10271 | MetaBreak: Special Token Manipulation Jailbreak | Coherence metadata attack vectors |
| 10.48550/arxiv.2510.15186 | MAGPIE: Multi-Agent Privacy Leakage Benchmark | 35-50% PII leakage in non-adversarial settings |

### DPO / Alignment
| DOI | Title | Relevance |
|-----|-------|-----------|
| 10.48550/arxiv.2510.09887 | Abductive Preference Learning | Counterfactual prompt discrimination |
| 10.48550/arxiv.2510.08256 | Mix- and MoE-DPO: Variational DPO | Multi-task preference specialization |

---

## Recommendations (Ranked: Impact↓ Innovation↓ Difficulty↑)

### 1. Failure-Mined APE Dimensions + Collective Confidence Router — HIGH/HIGH/MED
**Lenses**: Code Quality + Eval  
**Evidence**: APE (2510.06538): learns evaluation dimensions from LLM-judge failure cases; confidence-based ensemble adds perspectives only when uncertain (+3.3pp on RewardBench)  
**Problem**: Nash's review rubric is static. Developers implicitly judge comments on dimensions the agent never articulates (rollout risk, team style, "worth the churn"). Misalignment surfaces only post-comment.  
**Solution**: Mine recurring "unexpected negative" resolution patterns (comment marked outdated without adoption, suggestion heavily rewritten). Induce auxiliary evaluation dimensions from those clusters. At inference, a cheap uncertainty scorer invokes 1-2 mined dimensions only on low-confidence findings — bounded cost.  
**Implementation**:
- Persist per-comment outcomes from webhooks (applied, edited-merge, dropped, "N/A" replies)
- Periodic clustering job → LLM proposes named dimension + checklist question; human approves to versioned `review_dimensions` store
- Primary review draft → uncertainty scorer → conditionally append auxiliary judge calls
- CI replay on historical PRs validates new dimensions improve outcome correlation

---

### 2. Encoder-Decoder Review Context Split — HIGH/HIGH/HIGH
**Lenses**: Efficiency  
**Evidence**: E2D2 (2510.22852): encoder handles stable tokens, lightweight decoder iterates on noisy regions; MoNE (2510.05781): 50% parameter activation with no accuracy loss via top-k neuron selection  
**Problem**: Large PRs force the agent to re-read stable context (manifests, interfaces, imports) on every tool round-trip, inflating tokens per turn unnecessarily.  
**Solution**: Two-phase context split: (1) **Encoder pass** builds a compact canonical Context Capsule (structured JSON: dependency pins, public API deltas, risky paths, test coverage deltas) in one deterministic + LLM summarization step; (2) **Decoder pass** runs ReAct ONLY over the capsule + minimal needles, expanding to full files only on-demand.  
**Implementation**:
- Worker: `build_context_capsule(diff, files_touched) -> Pydantic model` persisted with content hashes
- Agent prompt rules: must cite `capsule_ref` fields before escalating to full-file fetch
- Tool `expand_window(start, end)` limits I/O; findings map to capsule keys for dedup + audit
- Capsule reusable across review re-runs for same PR commit SHA

---

### 3. Need-to-Know Tool Kernel (NKTK) — HIGH/HIGH/HIGH
**Lenses**: Security  
**Evidence**: MAGPIE (2510.15186): 35-50% PII leakage in non-adversarial multi-agent settings; task-completion incentives drive over-fetching of sensitive adjacent context  
**Problem**: ReAct loop tools (read file, search code) create a path for accidental credential/PII exfiltration into model traces, DB snapshots, and posted GitHub comments — especially because "complete review" pressure encourages over-fetching of `.env*`, `**/credentials*`, etc.  
**Solution**: `ToolPolicy` per job enforces purpose limitation: tools return minimized/redacted views by default. Broader reads require a structured justification record. Persistence layer uses post-kernel view only.  
**Implementation**:
- `ToolPolicy`: max bytes, path denlists (`.env*`, `credentials*`, `*.pem`), secret/PII detectors on tool returns
- Escalation token path: broader reads require structured justification stored with job
- Persistence redaction: DB snapshots use post-kernel view, not raw tool dumps
- Volume budgets per installation to block slow exfil patterns

---

### 4. Partial-Accept AST Signal-Level Preference Data — HIGH/HIGH/HIGH
**Lenses**: Code Quality + Eval  
**Evidence**: QiMeng-SALV (2510.19296): signal-level DPO with AST extraction of correct fragments from wrong completions; 7B model matches DeepSeek-V3 671B via partial-correctness signal  
**Problem**: Nash observes only coarse quality (comment posted or not). Developers cherry-pick, rename symbols, or accept the idea but not the patch — zero feedback on "right in the small."  
**Solution**: On merge, diff agent output vs landed hunk + AST alignment to tag accepted subtrees, rejected branches, "intent preserved" edits. Build pairwise preferences at granularity for offline eval and eventual SFT/DPO.  
**Implementation**:
- Webhook: capture final commit range; map inline review comments to file/line GitHub anchors
- tree-sitter/AST diff; fallback to line-level for non-AST formats
- Dataset rows: `(prompt_context, finding, suggested_patch, landed_patch, signal_mask)` with full/partial/rewrite/reject labels
- Monthly export → small ranker/critic training with secret-redaction guardrails

---

### 5. Prompt-Nonce Section Envelope (PNSE) — HIGH/MED/MED
**Lenses**: Security  
**Evidence**: MetaBreak (2510.10271): special tokens AND semantically similar regular tokens can rebuild conversation coherence cues; sanitizing just "special tokens" is insufficient  
**Problem**: Nash wraps PR hunks + tool outputs in a chat transcript. Attackers can embed fake "instruction ended; new instructions begin" patterns inside diff text that remain valid code but re-parse the model's task state.  
**Solution**: Per-job cryptographic nonces structurally bind every untrusted blob between server-issued delimiters containing the nonce. System policy states only those delimiters are authoritative; any similar-looking text without nonce is data, not control.  
**Implementation**:
- `job_nonce` derived at enqueue time, threaded through worker → prompt assembly
- Centralize prompt building: all hunks/tool returns via `envelope_untrusted(label, bytes, nonce)`
- Collision gate: if raw diff/tool text contains `job_nonce`, redact/reject hunk + emit security finding
- Monitor: "nonce collision attempts" metric

---

### 6. Versioned Repo Review PRD + Synthetic PR Fixtures — HIGH/MED/MED
**Lenses**: Code Quality + Eval  
**Evidence**: PRDBench (2510.24358): structured PRD criteria vs ad hoc rubrics; living benchmarks that evolve with capability. Continuous Benchmark Generation (2511.10049): semi-structured intent docs → auto-generated cases; eval as versioned code  
**Problem**: No first-class spec of what "good review" means for this repo. Quality degrades silently when prompts/models change. No regression tests.  
**Solution**: Optional `nash-review-prd.yaml` per repo: must-check requirements by PR type (dependency bump, auth touch, migration, etc.), expected evidence patterns, forbidden failure modes. Generator creates synthetic PR diffs + golden "expected finding shapes" from PRD.  
**Implementation**:
- Schema + validator in monorepo; documented for customers
- LLM generator expands PRD items → minimal diff fixtures + oracle checks (static rules + locked rubric)
- CI runner scores PRD coverage and regressions; `deep_eval` integration or dedicated worker job
- PRs that change PRD require benchmark delta in same change (eval-as-code)

---

### 7. Pre-Diff Structural Router (Pre-Gating) — HIGH/MED/MED
**Lenses**: Efficiency  
**Evidence**: Pre-Attention Expert Prediction (2511.10676): cheap pre-attention activations preserve routing rank; SP-MoE (2510.10302): bound prefetch depth with a policy layer  
**Problem**: ReAct loop burns turns "discovering" which parts of a PR matter (imports, configs, tests, migrations); tool calls arrive late and run sequentially.  
**Solution**: Before LLM round-1, deterministic structural extractor on diff + patch metadata emits a ranked tool-intent list. Agent consumes this as constraints (explore top-k intents first, cap parallel breadth).  
**Implementation**:
- Pure-Python `diff_router` step in ARQ worker job before `agent.run()`; outputs JSON `ranked_intents` with confidence + reason codes
- Router output injected into system prompt as non-negotiable first-N exploration order
- Metrics: tool calls avoided, time-to-first-finding, router precision replay on completed jobs

---

### 8. SLA-Governed Adaptive Prefetch Horizon — HIGH/MED/HIGH
**Lenses**: Efficiency  
**Evidence**: ExpertFlow (2510.26730): continuously adjusts prediction horizon from bandwidth+runtime stats; SP-MoE cutoff-layer policy; MoE-SpeQ roofline guidance  
**Problem**: Uncontrolled speculative I/O can amplify queue latency under Redis/GitHub pressure and cause bursty 429s — especially on large PRs.  
**Solution**: Maintain horizon H (max pipelined tool requests) updated from median tool latency, p95 GitHub latency, installation rate-limit budget, ARQ queue depth, and soft per-job SLA.  
**Implementation**:
- `PrefetchController` module in worker loop: `H = f(p95_github_ms, remaining_budget, queue_wait_s)` with hard clamps
- httpx/GitHub wrapper feeds live latency + rate-limit telemetry into controller (in-memory ring buffer)
- Batched GitHub calls (async gather) up to H; cancellable on first high-value result
- ARQ metadata: deprioritize speculative work when cluster is hot

---

### 9. Multi-Turn Maintainer Simulation Suite — MED/HIGH/MED
**Lenses**: Code Quality + Eval  
**Evidence**: RECODE-H (2510.06186): multi-turn simulated human feedback; 5-level feedback hierarchy; one-shot eval misses collaborative repair cycles  
**Problem**: Single-pass reviews can look good but fall apart under clarification. Nash has no metric for trajectory quality: iterations to reach actionable thread, churn, escalation patterns.  
**Solution**: Offline harness where a second model role-plays a maintainer (L1 vague pushback → L5 concrete repro + constraints). Review agent may revise findings under token budget. Score turns-to-satisfy, final patch acceptability, non-regression.  
**Implementation**:
- Scenario bank from real anonymized threads + synthetic PRs; fixed seeds
- Multi-turn orchestrator with K-round limit
- Metrics: task success, revision stability, toxicity/insistence on wrong claims, tool-call efficiency
- Nightly job + release gate; trajectories feed APE failure-mining pipeline (proposal 1)

---

### 10. Buddy-Artifact Fallback Graph — MED/HIGH/MED
**Lenses**: Efficiency  
**Evidence**: BuddyMoE (2511.10054): paired redundant experts substituted on prefetch miss with minimal accuracy loss; MoE-SpeQ amortization gate  
**Problem**: GitHub file fetches/searches fail or stall (rate limits, large files, renamed paths), forcing retries and long sequential chains.  
**Solution**: Per-job buddy map: primary asset → ordered substitutes (HEAD → merge-base → LCA blob → ripgrep-extracted window → similar path by Levenshtein). Auto-downgrade on miss/timeout with annotated confidence.  
**Implementation**:
- `fetch_file`/`search_code` tools return structured `{source_tier, substitute_of, truncation, sha}`
- Buddy resolution in Python with Redis-cached GitHub responses
- Amortization gate: use expensive substitutes only if elapsed time or stalls exceed threshold
- Log substitution outcomes to tune buddy policy

---

### 11. Attested Diff Segmentation (ADS) — MED/MED/MED
**Lenses**: Security  
**Evidence**: CompressionAttack (previously known): adversarial edits transform benign compressed representation into malicious instruction (82-87% ASR); integrity loss between human-visible source and model-visible prompt  
**Problem**: Any future summarization/compaction of diffs could allow an attacker to target the transform boundary — the model reviews a different effective program than GitHub shows.  
**Solution**: Diff pipeline treats every segment as integrity-critical ETL: per-hunk stable IDs + cryptographic hashes in the prompt. Agent findings must cite segment IDs; mismatches trigger re-fetch and re-attest before posting.  
**Implementation**:
- Canonical normalization for diff hunks (line endings, no reordering)
- Per-hunk digests at ingest; stored with job payload
- Prompt compiler emits SEGMENTS manifest; tool reads re-verify digest after fetch
- Mismatch: abort posting for that region or downgrade to "needs manual verification"

---

### 12. Cooperative-Access Leakage Auditor (CALA) — MED/MED/MED
**Lenses**: Security  
**Evidence**: MAGPIE (2510.15186): non-adversarial multi-agent settings still produce manipulation/power-seeking behaviors; leakage correlates with tool affordances  
**Problem**: Even with prompt hardening, ReAct loop can drift into over-broad repo exploration, increasing sensitive context load and the risk of accidentally quoting secrets in inline comments.  
**Solution**: Second-channel trajectory audit after reasoning but before posting: scores privacy risk + scope creep from tool graph + retrieved byte counts + entropy/secret hits. Block or redact high-risk spans before GitHub submission.  
**Implementation**:
- Structured trace: each tool call's purpose, paths, bytes returned, redaction flags
- Rules + optional lightweight scorer: flags many unrelated paths, PII pattern density, comment text overlapping tool payload high-entropy tokens
- Gate GitHub submission: high score → replace inline body with scrubbed version + internal incident fields
- Aggregate risk dashboards via existing WARN log monitoring

---

## Meta-Architectural Insights from This Session

### Cross-Lens Convergence Points
1. **"Predict before blocking" is the unifying efficiency pattern**: Pre-Attention routing, ExpertFlow adaptive horizon, SLA-governed prefetch, Pre-Diff Structural Router, and BuddyMoE all express the same meta-principle — predict next computational needs speculatively to hide latency. This is now a **repeating architectural pattern** across 3 successive research sessions.

2. **Coherence metadata (not just token content) is the attack surface**: MetaBreak shows that structural cues about "where instructions end" — not just the content of those instructions — are weaponizable. PNSE addresses this directly by cryptographically binding all instruction-vs-data boundaries.

3. **Coarse-grained feedback is the data bottleneck**: DPO-F+, QiMeng-SALV, RECODE-H, and APE all point to the same gap — systems learn from coarse binary signals (accepted/rejected) when they need **granular partial-correctness signals** (which subtree was right, which turn resolved the issue). Partial-Accept AST Signal Preferences directly attacks this.

4. **Eval must be first-class code**: PRDBench, Continuous Benchmark Generation, and RECODE-H all converge on treating evaluation as maintainable, versioned, testable code (not post-hoc manual review). Versioned Review PRD closes this gap for Nash.

### Potential Future Paper Direction (from cross-session synthesis)
- Sessions 2026-05-06 and 2026-05-08 both independently discovered that: (a) evaluation rubric quality gates outcome quality more than model quality, and (b) partial-signal training outperforms binary pass/fail. A novel contribution: **"Self-improving evaluation infrastructure for LLM code review agents"** that combines IRT discrimination analysis, AST-granular preference extraction, and APE-style failure-mined dimension induction into a continuously self-calibrating eval stack. No unified system with all three components exists in the literature.

---

*Report generated by Nash AI daily research cron. Artiforge: ERROR. Zotero: credentials invalid. R2: archived.*
