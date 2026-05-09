# LLM Research Innovation Recommendations — 2026-05-09

**Run date:** 2026-05-09 (daily cron)
**Orchestrator:** Sonnet 4.6 (composer-2-fast)
**Research lenses:** Code Quality · Prompt Evaluation · Efficiency · Security/Injection
**New papers found:** ~51 (deduplicated)
**New recommendations:** 10

> Note: User-requested models (GPT 5.5 Medium, Opus 4.7 High, Opus 4.6 High, Sonnet 4.6 High) are not available as Task subagent slugs. All lenses run on composer-2-fast. Please update the Cursor Cloud model roster to unlock role-differentiated model debate. Zotero API key is still invalid — please regenerate at https://www.zotero.org/settings/keys and update the `ZOTERO_API_KEY` secret. Artiforge MCP is in ERROR state and unavailable for agent orchestration.

---

## New Recommendations (sorted: Impact↓ Innovation↓ Difficulty↑)

### 1. FCV-Resistant Security Synthesis Pass
**Category:** Security | **Impact:** HIGH | **Innovation:** HIGH | **Difficulty:** HIGH
**Grounding papers:** `10.48550/arxiv.2510.17862` (When "Correct" Is Not Safe), `10.48550/arxiv.2510.21272` (PMDetector)

**Proposal:** Add a dedicated post-review sub-phase that evaluates whether the PR, despite passing CI, introduces a "Functionally Correct yet Vulnerable" (FCV) pattern. The FCV-Attack paper demonstrates 40.7% attack success rate on code agents with a single black-box query — PRs can be crafted to pass all tests while silently introducing CWE-class vulnerabilities. Implement PMDetector's three-stage chain as a tool call: (1) static taint analysis narrows the search space, (2) Claude reasons over taint flows, (3) static validator confirms. This costs ~$0.03/audit with Gemini 2.5-flash in the paper's benchmark.

**Implementation:** New `security_synthesis_pass` tool in the ReAct loop that runs after standard review; only activates on PRs with security-relevant diffs (auth, crypto, I/O). Returns a structured FCV risk score and specific CWE candidates.

---

### 2. Content-Injection Factual Guard
**Category:** Security | **Impact:** HIGH | **Innovation:** HIGH | **Difficulty:** MEDIUM
**Grounding papers:** `10.48550/arxiv.2510.11238` (Attacks by Content), `10.48550/arxiv.2510.00451` (PromptShield)

**Proposal:** Current injection defenses scan for instruction-style text ("ignore previous instructions"). Attacks by Content demonstrates a blind spot: false factual claims in PR comments/docstrings ("This function is deprecated and safe to ignore") steer the reviewer without triggering any instruction detector. Add a semantic consistency check tool that validates whether factual claims in code comments are consistent with actual code behavior — comparing the claim against AST structure, call graph, and return types. PromptShield's ontology-driven approach validates inputs against an expected schema, applicable to diff format validation before LLM processing.

**Implementation:** Pre-processing tool call that extracts factual claims from comments/docstrings, then verifies each claim against the corresponding code; flags inconsistencies as `SUSPICIOUS_COMMENT` with severity tied to how much the inconsistency could mislead a reviewer.

---

### 3. Cross-Repo Semantic Bug Pattern Propagation
**Category:** Code Quality | **Impact:** HIGH | **Innovation:** HIGH | **Difficulty:** MEDIUM
**Grounding papers:** `10.48550/arxiv.2510.14036` (BUGSTONE), `10.48550/arxiv.2510.26086` (LLMBisect)

**Proposal:** BUGSTONE identifies recurring pattern bugs (RPBs) — from a single patched seed, it found 22K+ issues in the Linux kernel with 92.2% precision. LLMBisect achieves 38% better accuracy at identifying which commit introduced a bug. Combine these: when the review agent finds a bug, (1) generate a semantic search query from the bug pattern, (2) check if the same pattern exists elsewhere in the repo, (3) annotate the finding with sibling occurrences and the blame commit. This makes findings dramatically more actionable — instead of "this function may have a null dereference," the agent says "this null dereference pattern also appears in auth.py:142 and api_client.py:67, introduced in commit a3f2b1."

**Implementation:** New `pattern_propagation` tool call: takes a structured bug description → generates grep/AST query → returns sibling locations + git log for each. Lightweight enough to run on every finding with severity ≥ MEDIUM.

---

### 4. Output-Side Post-Generation Verification Gate
**Category:** Security | **Impact:** HIGH | **Innovation:** MEDIUM | **Difficulty:** LOW
**Grounding papers:** `10.48550/arxiv.2510.01529` (Bypassing Prompt Guards)

**Proposal:** Bypassing Prompt Guards demonstrates that lightweight input classifiers can be evaded by encoding injections that the main LLM decodes. The paper advocates shifting defense to the output side: verify what the agent *proposes to post*, not what it reads. Add a post-generation verification step that: (1) validates the proposed comment against a structured schema (must have severity, evidence anchor, and reproduction signal), (2) checks for anomalous patterns like sudden scope expansion, self-referential instructions, or severity escalation inconsistent with the diff, (3) optionally routes to a lightweight secondary classifier. This is additive and non-blocking (flag for human review vs. suppress).

**Implementation:** Post-generation schema validator + behavioral anomaly detector on the `proposed_comments` list before posting to GitHub Review Comments API. Low difficulty because it's purely additive post-processing with no changes to the core ReAct loop.

---

### 5. Online Accept/Reject-Driven Rubric Elicitation
**Category:** Evaluation | **Impact:** HIGH | **Innovation:** HIGH | **Difficulty:** MEDIUM
**Grounding papers:** `10.48550/arxiv.2510.07284` (OnlineRubrics)

**Proposal:** OnlineRubrics dynamically elicits rubric criteria from pairwise comparisons during RL, achieving 8% gain over static rubrics and preventing reward-hacking drift. Apply this to the PR review context: track developer interactions (suggestion application rate, comment reaction, PR approval correlation) as pairwise preference signals. When developers consistently dismiss one class of findings but act on another, update rubric criterion weights dynamically. This prevents the common failure mode where the agent optimizes for criteria developers don't value (e.g., pedantic style comments over actionable security findings).

**Implementation:** Background job that processes GitHub webhook events for suggestion applications, comment dismissals, and PR approval timing. Computes criterion-level preference scores. Updates evaluation rubric weights via a versioned `rubric_weights.json` that is loaded at review initialization.

---

### 6. Shared-KV PR Diff Architecture for Review Serving
**Category:** Efficiency | **Impact:** HIGH | **Innovation:** MEDIUM | **Difficulty:** HIGH
**Grounding papers:** `10.48550/arxiv.2511.06010` (MoSKA — Mixture of Shared KV Attention)

**Proposal:** MoSKA achieves up to 538× throughput improvement by separating per-request KV from massively reused shared KV (document prefixes). The PR diff + system prompt are static across every tool call within a review session — they're read-only and never change. Restructure the inference serving layer to treat this static prefix as a shared compute-bound GEMM batch rather than per-request memory-bound GEMVs. This is the highest-ROI efficiency change not yet exploited by standard vLLM deployments.

**Implementation:** Infrastructure change: encode the PR diff + system prompt as a shared KV block in the serving layer (vLLM prefix caching already approximates this, but MoSKA's formal separation achieves far higher utilization). Requires changes to how the ARQ worker structures requests to the LLM provider.

---

### 7. Agentic Tool-Call History Distillation
**Category:** Efficiency | **Impact:** HIGH | **Innovation:** MEDIUM | **Difficulty:** MEDIUM
**Grounding papers:** `10.48550/arxiv.2510.00615` (ACON), `10.48550/arxiv.2510.10448` (RECON)

**Proposal:** ACON compresses both environment observations and tool-call interaction histories in agentic loops, achieving 26–54% peak token reduction with 95%+ task accuracy. RECON integrates condensation inside the RL reasoning loop, reducing context by 35% while improving accuracy. As the ReAct loop accumulates tool results (file contents, git history, dependency graphs), the context grows proportionally. Add a distillation step between turns that compresses prior tool observations into a compact summary while preserving key findings.

**Implementation:** Between-turn compressor agent: receives `[tool_name, args, result]` history and outputs a structured summary. Can be a small model distilled from Claude or a simple extractive summary of non-redundant information. Configurable compression budget per review based on PR size.

---

### 8. Multi-Objective Vectorized Review Alignment
**Category:** Evaluation | **Impact:** MEDIUM | **Innovation:** HIGH | **Difficulty:** HIGH
**Grounding papers:** `10.48550/arxiv.2510.01167` (MAH-DPO — Multi-Aspect Hierarchical DPO)

**Proposal:** MAH-DPO uses vectorized multi-objective DPO with per-dimension rewards (e.g., security/readability/correctness) and inference-time user weighting. Apply to code review: collect preference signals per review dimension (security finding quality, readability suggestion quality, actionability of suggestions) from developer interactions. Train with vectorized DPO where each rejection reason is mapped to a specific dimension. At inference time, weight dimensions by repository context (security-critical repos get 3× security weight; style-first repos get high readability weight).

**Implementation:** Requires (1) fine-tuning data collection with dimension-tagged preferences, (2) modified DPO training objective, (3) inference-time dimension weight vector passed as system prompt metadata. High difficulty due to fine-tuning requirement, but unlocks per-repo customization of review focus.

---

### 9. Quarantine-and-Validate Session Context Memory
**Category:** Security | **Impact:** MEDIUM | **Innovation:** HIGH | **Difficulty:** MEDIUM
**Grounding papers:** `10.48550/arxiv.2510.02373` (A-MemGuard)

**Proposal:** A-MemGuard demonstrates that agents with memory can be attacked via dormant injected records that activate in specific contexts, creating self-reinforcing error cycles (95% attack success without defense; <5% with). If Nash AI caches any per-repo or per-PR context (repository summaries, past review patterns, dependency maps), that cache is an injection target. Implement a dual-memory architecture: (1) quarantine memory receives all inputs from untrusted sources (PR content, file reads), (2) active memory contains only validated, consensus-checked findings. Before any quarantine item influences the active reasoning chain, it must pass a validation check against the active memory contents.

**Implementation:** Modify the review agent's context construction to distinguish `trusted_context` (installation settings, GitHub API metadata) from `quarantine_context` (diff content, file reads, PR description). The ReAct loop reasons over both but flags any action that is primarily justified by quarantine-only evidence.

---

### 10. Mutation-Score-Gated Review Quality Evaluation
**Category:** Evaluation | **Impact:** MEDIUM | **Innovation:** MEDIUM | **Difficulty:** MEDIUM
**Grounding papers:** `10.1002/smr.70034` (MutScore), `10.48550/arxiv.2510.19898` (BugPilot)

**Proposal:** MutScore shows that mutation score (not branch/statement coverage) is the discriminating metric for code-generation benchmark quality. BugPilot generates realistic bugs by having SWE agents unintentionally break tests. Apply this to review quality evaluation: generate a synthetic mutation corpus for each repository (BugPilot-style) and use the PR reviewer's ability to detect those mutations as the primary eval metric. Replace the current qualitative eval ("did the review seem good?") with a quantitative mutation-detection rate. This becomes the CI gate for review quality regression.

**Implementation:** Periodic job that (1) generates N synthetic bugs from recent commit history, (2) submits them as synthetic PRs to the review agent, (3) measures mutation detection rate, (4) alerts if rate drops below threshold. BugPilot's methodology of using SWE-agent failures as mutation seeds makes this practical without manual annotation.

---

## Session Meta-Insights

### Cross-Lens Convergence: Output Verification as the Frontier
Three independent lenses converged on the same structural gap this session:
- **Security lens:** Output-side verification is more robust than input sanitization (Bypassing Prompt Guards)
- **Eval lens:** Cross-verifier annotation (one LLM auditing another's output labels) gives 58% κ improvement
- **Code quality lens:** Structural oracles verifying AI-generated code structure (NITR) outperform pure correctness checks
- **Efficiency lens:** MoSKA separates static shared-prefix computation from per-turn output generation

**Conclusion:** The AFTER-THE-LLM verification layer is the frontier. Pre-processing is well-studied; post-generation chain verification is the next architectural boundary.

### Recurring Architectural Pattern: Predict-Before-Execute (5th consecutive session)
The "predict before blocking" pattern continues in this session through DVI (draft head trained on accept/reject decisions), SeqTopK (budget assignment before token routing), and ACON (compress before accumulate). This is now a confirmed primary architectural principle across 5 sessions — any new component in the review pipeline should ask "what can be pre-predicted to hide latency?"

### FCV Threat Model (Novel, First Session)
"Functionally Correct yet Vulnerable" is a new threat category introduced this session. Code that passes all CI gates can still be a security regression. This is distinct from all prior security recommendations (which addressed injection, jailbreaks, or data poisoning). It directly expands Nash AI's required review surface.

### Potential Future Paper (6th consecutive session confirmation)
The integrated architecture of: FCV detection via static-taint/LLM-reason/static-validate + online rubric elicitation from developer accept/reject signals + content-injection factual consistency checking + output-side verification gate forms a novel "adversarially robust, self-calibrating code review agent" architecture. No single paper in the literature combines all four. Six sessions now independently confirm this gap across code quality, security, and evaluation lenses.

---

## New Papers Indexed This Session

### Code Quality
| DOI | Title (abbreviated) |
|-----|---------------------|
| 10.48550/arxiv.2603.27745 | NITR — Maintainability Benchmark for AI-Generated Edits |
| 10.48550/arxiv.2510.18131 | BlueCodeAgent — Red+Blue Teaming for CodeGen Security |
| 10.48550/arxiv.2510.14036 | BUGSTONE — Recurring Pattern Bug Discovery at Scale |
| 10.48550/arxiv.2510.20739 | LLM Triage of Taint Flows from Dynamic Analysis |
| 10.48550/arxiv.2511.04824 | Agentic Refactoring — Empirical Study |
| 10.48550/arxiv.2510.19898 | BugPilot — Realistic Synthetic Bugs for SWE Training |
| 10.48550/arxiv.2510.21413 | Context Engineering for AI Agents — AGENTS.md Study |
| 10.48550/arxiv.2510.26086 | LLMBisect — Bug Bisection via Multi-Stage LLM Pipeline |
| 10.48550/arxiv.2510.21272 | PMDetector — Static Taint + LLM Hybrid Vulnerability Detection |
| 10.48550/arxiv.2510.27675 | Few-Shot Example Selection for LLM Vulnerability Detection |
| 10.48550/arxiv.2511.01104 | HarnessLLM — RL-Trained Test Harness Generation |
| 10.24251/hicss.2025.902 | AVASST — LLMs Accelerating Software Standards Compliance |
| 10.48550/arxiv.2510.09721 | Comprehensive Survey on LLM-SE Benchmarks and Solutions |
| 10.48550/arxiv.2510.18936 | SBAN — Multi-Dimensional Dataset for LLM Code Mining |

### Prompt Evaluation
| DOI | Title (abbreviated) |
|-----|---------------------|
| 10.48550/arxiv.2510.07284 | OnlineRubrics — Dynamic Rubric Elicitation from Pairwise Comparisons |
| 10.48550/arxiv.2511.09785 | AI Annotation Orchestration — Cross-Verifier LLM Labeling |
| 10.48550/arxiv.2510.13888 | ProofGrader — Fine-Grained Ensemble Evaluation |
| 10.48550/arxiv.2511.12573 | CausalLenBias — Counterfactual Pairs for Length Bias Removal |
| 10.48550/arxiv.2510.05283 | HARMO — Hybrid Rule+Learned Reward + Multi-Aspect Signals |
| 10.48550/arxiv.2510.10963 | APLOT — Optimal Transport Adaptive Margins for DPO |
| 10.48550/arxiv.2510.01167 | MAH-DPO — Multi-Aspect Hierarchical Vectorized DPO |
| 10.48550/arxiv.2510.20413 | AuxDPO — Fixing DPO Preference-Order Reversal |
| 10.48550/arxiv.2511.19829 | UEIPO — Execution-Free Multi-Dimensional Prompt Optimizer |
| 10.48550/arxiv.2510.14381 | PromptPoison — Feedback-Channel Poisoning Defense |
| 10.48550/arxiv.2510.06092 | FA-IRL — Failure-Aware Inverse RL for Latent Rewards |
| 10.1002/smr.70034 | MutScore — Mutation Score as Code Benchmark Quality Metric |

### Efficiency
| DOI | Title (abbreviated) |
|-----|---------------------|
| 10.48550/arxiv.2510.00615 | ACON — Context Compression for Long-Horizon LLM Agents |
| 10.48550/arxiv.2511.06010 | MoSKA — Mixture of Shared KV Attention |
| 10.48550/arxiv.2510.02312 | KaVa — Latent Reasoning via Compressed KV-Cache Distillation |
| 10.48550/arxiv.2510.10448 | RECON — Reasoning with Condensation for Efficient RAG |
| 10.48550/arxiv.2510.05421 | DVI — Draft, Verify, and Improve Speculative Decoding |
| 10.48550/arxiv.2510.26843 | CAS-Spec — Cascade Adaptive Self-Speculative Decoding |
| 10.48550/arxiv.2511.06494 | SeqTopK — Route Experts by Sequence not Token |
| 10.48550/arxiv.2510.03293 | LASER — Plug-and-Play MoE Load Balancing |
| 10.48550/arxiv.2510.02345 | Breaking the MoE Trilemma — Dynamic Expert Clustering |
| 10.48550/arxiv.2510.14853 | Rewiring Experts on the Fly — Test-Time MoE Rerouting |
| 10.48550/arxiv.2511.07419 | RoMA — Routing Manifold Alignment for MoE LLMs |
| 10.48550/arxiv.2510.14392 | FairBatching — Fairness-Aware Batch Formation |
| 10.48550/arxiv.2510.13223 | BanaServe — Dynamic Disaggregated LLM Serving |
| 10.48550/arxiv.2511.20982 | DOPD — Dynamic Optimal Prefill/Decoding Disaggregation |
| 10.48550/arxiv.2510.18672 | Reasoning LLM Inference Serving — Empirical Study |

### Security / Injection
| DOI | Title (abbreviated) |
|-----|---------------------|
| 10.48550/arxiv.2510.11238 | Attacks by Content — Fact-Checking as AI Security |
| 10.48550/arxiv.2510.17862 | When "Correct" Is Not Safe — FCV-Attack on Code Agents |
| 10.48550/arxiv.2510.00451 | PromptShield — Ontology-Driven Input Validation |
| 10.48550/arxiv.2510.02373 | A-MemGuard — Proactive Defense for LLM Agent Memory |
| 10.48550/arxiv.2510.22944 | Is Your Prompt Poisoning Code? — Defect Induction Rates |
| 10.48550/arxiv.2511.13341 | OSS Supply Chain LLM Backdoor Risk Framework |
| 10.48550/arxiv.2510.07192 | Poisoning Attacks Need Near-Constant Samples |
| 10.48550/arxiv.2510.01529 | Bypassing Prompt Guards in Production |
| 10.48550/arxiv.2510.27140 | Mobile LLM Agents and Untrusted Third-Party Channels |
| 10.48550/arxiv.2510.22620 | Breaking Agent Backbones — Backbone Security Evaluation |

---

*R2 storage: `reports/2026-05-09.md` · `manifests/2026-05-09.json`*
*Zotero: SKIPPED — invalid API key. Regenerate at https://www.zotero.org/settings/keys*
*Artiforge: SKIPPED — MCP server in ERROR state*
