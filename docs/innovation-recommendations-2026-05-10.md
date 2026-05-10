# Nash AI — LLM Research Innovation Report
## Date: 2026-05-10 (Daily Cron)

---

## New Papers Reviewed: 37

### Code Quality & Code Review (11 papers)
| DOI | Title | Year | Key Contribution |
|-----|-------|------|-----------------|
| 10.48550/arxiv.2601.19072 | HalluJudge: Reference-Free Hallucination Detection for Context Misalignment in Code Review Automation | 2026 | Reference-free detection of context-misaligned review comments against PR diffs before reaching developers |
| 10.48550/arxiv.2601.19494 | AACR-Bench: Evaluating Automatic Code Review with Holistic Repository-Level Context | 2026 | Benchmark for automatic code review with holistic repo context, not just diff-only |
| 10.48550/arxiv.2601.19138 | AgenticSCR: An Autonomous Agentic Secure Code Review for Immature Vulnerabilities Detection | 2026 | Agentic pipeline specialized to early-stage/immature vulnerability signals beyond generic comment generation |
| 10.48550/arxiv.2603.00539 | Are LLMs Reliable Code Reviewers? Systematic Overcorrection in Requirement Conformance Judgement | 2026 | Characterizes systematic overcorrection behavior that undermines trust in LLM conformance judgments |
| 10.48550/arxiv.2603.26664 | Learning to Commit: Generating Organic Pull Requests via Online Repository Memory | 2026 | Organic PR generation using repository memory so changes align with project history/conventions |
| 10.1016/j.engappai.2025.113410 | Fine-tuning a vulnerability-specific LLM for hybrid software vulnerability detection | 2026 | Hybrid detector combining vulnerability-tuned LLM with broader detection tools |
| 10.48550/arxiv.2602.10487 | Following Dragons: Code Review-Guided Fuzzing | 2026 | Review-derived guidance steers fuzzing toward human-identified risk areas |
| 10.48550/arxiv.2601.10942 | Change And Cover: Last-Mile Pull Request-Based Regression Test Augmentation | 2026 | PR-centric approach to augment regression tests at integration time |
| 10.48550/arxiv.2603.27333 | ComBench: A Repo-level Real-world Benchmark for Compilation Error Repair | 2026 | Repo-level execution-verified benchmark showing syntax fix >> semantic fix for LLMs |
| 10.48550/arxiv.2603.00897 | Detect Repair Verify for Securing LLM Generated Code: A Multi-Language Empirical Study | 2026 | Treat securing generated code as explicit detect/repair/verify loop not one-shot generation |
| 10.21203/rs.3.rs-6955423/v1 | The Debugging Decay Index: Rethinking Debugging Strategies for Code LLMs | 2025 | Quantifies exponential decay in iterative LLM debugging; proposes DDI + reset-trigger points |

### Prompt Eval / Judges / Rubrics (8 papers)
| DOI | Title | Year | Key Contribution |
|-----|-------|------|-----------------|
| 10.48550/arxiv.2603.29403 | Security in LLM-as-a-Judge: A Comprehensive SoK | 2026 | First SoK for LLM judge security—judges as attack target, channel, and defensive component |
| 10.48550/arxiv.2603.28376 | Marco DeepResearch: Unlocking Efficient Deep Research Agents via Verification-Centric Design | 2026 | End-to-end verification-centric agent (synthesis, trajectory, inference-time scaling) |
| 10.48550/arxiv.2603.25770 | ReCUBE: Evaluating Repository-Level Context Utilization in Code Generation | 2026 | Benchmark explicitly targeting how models use repository context in code tasks |
| 10.48550/arxiv.2601.03444 | Grading Scale Impact on LLM-as-a-Judge: Human-LLM Alignment Is Highest on 0-5 Scale | 2026 | Empirical study: 0-5 scale maximizes human–LLM agreement in judge scoring |
| 10.48550/arxiv.2603.29919 | SkillReducer: Optimizing LLM Agent Skills for Token Efficiency | 2026 | Prompt/skill compression with separate generator vs judge models + verifier-calibrated LLM judging |
| 10.48550/arxiv.2602.14069 | Open Rubric System: Scaling Reinforcement Learning with Pairwise Adaptive Rubric | 2026 | Pairwise adaptive rubric framing for scaling RL reward signals |
| 10.48550/arxiv.2603.01562 | RubricBench: Aligning Model-Generated Rubrics with Human Standards | 2026 | Benchmark oriented toward aligning auto-produced rubrics with human-written rubric standards |
| 10.48550/arxiv.2602.13110 | SCOPE: Selective Conformal Optimized Pairwise LLM Judging | 2026 | Pairwise judging with conformal statistical reliability framing for calibrated uncertainty |

### Efficiency (8 papers)
| DOI | Title | Year | Key Contribution |
|-----|-------|------|-----------------|
| 10.48550/arxiv.2603.27469 | KV Cache Quantization for Self-Forcing Video Generation: 33-Method Empirical Study | 2026 | Large empirical map (33 variants) for KV compression tradeoffs: VRAM vs runtime |
| 10.48550/arxiv.2603.29494 | VecAttention: Vector-wise Sparse Attention for Accelerating Long Context Inference | 2026 | Fine-grained vertical-vector sparsity for accuracy–efficiency beyond coarse sparse attention |
| 10.1145/3731569.3764849 | DCP: Addressing Input Dynamism in Long-Context Training via Dynamic Context Parallelism | 2025 | Dynamic blockwise device mapping with hypergraph planning for variable-length context training |
| 10.1145/3746027.3755754 | Input Domain Aware MoE: Decoupling Routing Decisions from Task Optimization | 2025 | Probabilistic input-space partitioning for clearer expert specialization + load balance |
| 10.21203/rs.3.rs-8374807/v3 | EPMORE: Explainable Process Mixture-of-Experts | 2026 | Hierarchical dimensional-expansion process MoE for interpretability + inference efficiency |
| 10.48550/arxiv.2603.26498 | Rocks, Pebbles and Sand: Modality-Aware Scheduling for Multimodal LLM Inference | 2026 | Modality-aware scheduling with prioritization to reduce TTFT and head-of-line blocking |
| 10.24963/ijcai.2025/690 | RotateKV: Accurate and Robust 2-Bit KV Cache Quantization via Outlier-Aware Adaptive Rotations | 2025 | Rotation-based 2-bit KV quantization with RoPE compatibility + attention-sink awareness |
| 10.1145/3746027.3758181 | TinyServe: Query-Aware Cache Selection for Efficient LLM Serving | 2025 | Query-aware partial KV page loading using bounding-box metadata + fused CUDA path |

### Security & Injection (11 papers)
| DOI | Title | Year | Key Contribution |
|-----|-------|------|-----------------|
| 10.48550/arxiv.2603.30016 | Architecting Secure AI Agents: Defenses Against Indirect Prompt Injection | 2026 | Frames indirect injection as systems-design problem—orchestration, policy enforcement, constrained contexts |
| 10.48550/arxiv.2603.28013 | Kill-Chain Canaries: Stage-Level Tracking of Prompt Injection | 2026 | Cryptographic canaries across EXPOSED→PERSISTED→RELAYED→EXECUTED kill-chain stages |
| 10.48550/arxiv.2603.27517 | A Systematic Taxonomy of Security Vulnerabilities in the OpenClaw AI Agent Framework | 2026 | Cross-layer composition beats isolated sandbox/policy—gateway, host, plugin provenance taxonomy |
| 10.48550/arxiv.2603.28345 | Crossing the NL/PL Divide: Information Flow Analysis Across NL/PL Boundary in LLM-Integrated Code | 2026 | Formalizes prompt→model→executable-output chains reviving injection at NL/PL boundary |
| 10.48550/arxiv.2603.28988 | Attesting LLM Pipelines: Enforcing Verifiable Training and Release Claims | 2026 | Cryptographic attestation + promotion gate binding evidence to claims before trusted admission |
| 10.48550/arxiv.2603.27204 | Elementary My Dear Watson: Detecting Malicious Skills via Neuro-Symbolic Reasoning | 2026 | Treats agent skills as supply-chain unit with distributed malicious evidence via value-flow graphs |
| 10.48550/arxiv.2603.27277 | Codebase-Memory: Tree-Sitter Knowledge Graphs for LLM Code Exploration via MCP | 2026 | Connects MCP-wide tool trust to operational verification beyond prompt-level defenses |
| 10.48550/arxiv.2603.28166 | Evaluating Privilege Usage of Agents with Real-World Tools (GrantBox) | 2026 | Empirical: real MCP-integrated privilege surfaces dominate agent compromise rates |
| 10.1007/s10462-025-11389-2 | Safeguarding Large Language Models: A Survey | 2025 | Broad synthesis tying jailbreak/adversarial literature to guardrail lifecycle framing |
| 10.1101/2025.09.17.676717 | A Biosecurity Agent for Lifecycle LLM Biosecurity Alignment | 2025 | Defense-in-depth: dataset sanitization + DPO + runtime guardrails + automated red-teaming |

---

## Top Recommendations for Nash AI Code Review Agent
### (Ranked: Impact↓, Innovation↓, Difficulty↑)

| # | Title | Impact | Innovation | Difficulty | Category | Grounding Papers |
|---|-------|--------|-----------|---------|----------|-----------------|
| 1 | Kill-Chain Canary Injection Tracker | HIGH | HIGH | MED | security | Kill-Chain Canaries (2603.28013) |
| 2 | Reference-Free Review Hallucination Guard | HIGH | HIGH | MED | code_quality | HalluJudge (2601.19072) |
| 3 | Detect-Repair-Verify for Suggestion Blocks | HIGH | HIGH | MED | code_quality | ComBench (2603.27333) + Detect Repair Verify (2603.00897) |
| 4 | NL/PL Boundary Taint Tracking for Suggestions | HIGH | HIGH | HIGH | security | NL/PL Divide (2603.28345) |
| 5 | Overcorrection Calibration Pass for Conformance Judgments | HIGH | MED | MED | eval | Reliable Code Reviewers (2603.00539) |
| 6 | Organic Repository Memory for Context-Appropriate Review | MED | HIGH | MED | code_quality | Learning to Commit (2603.26664) |
| 7 | DDI Iteration Budget + Decay-Triggered Exploration Reset | HIGH | MED | LOW | efficiency | Debugging Decay Index (rs-6955423) |
| 8 | 0-5 Severity Rubric Standardization | MED | MED | LOW | eval | Grading Scale Impact (2601.03444) |
| 9 | LLM Judge Security Hardening via SoK Taxonomy | MED | HIGH | MED | security | Security in LLM-as-Judge SoK (2603.29403) |

---

## Detailed Recommendation Specs

### 1. Kill-Chain Canary Injection Tracker (HIGH/HIGH/MED)
**Problem:** Our ReAct agent processes untrusted PR diff content and tool outputs. Current defenses only check at input or output, not intermediate stages. Injection that crosses only one stage might still cause harm.
**Proposed solution:** Embed lightweight cryptographic canary markers at each pipeline stage (EXPOSED = diff ingested; PERSISTED = stored in context memory; RELAYED = passed to tool call; EXECUTED = acted upon by model). Track propagation. Break the chain at RELAYED if the canary originated from untrusted content.
**Components to change:** `apps/api/src/app/agent/` (ReAct loop), new `apps/api/src/app/webhooks/injection_canary.py`
**Innovation:** Applies kill-chain instrumentation (borrowed from enterprise security) to LLM agent pipelines — not yet present in any production code review agent.

### 2. Reference-Free Review Hallucination Guard (HIGH/HIGH/MED)
**Problem:** Our agent posts review comments that may not be grounded in the actual diff. HalluJudge shows this is a prevalent problem even for frontier models.
**Proposed solution:** Before posting each review comment, run a reference-free misalignment check: does the claim in the comment have an actual anchor in the diff? A lightweight classifier (or small LLM call) returns a misalignment score. Comments above threshold are either suppressed or downgraded to advisory.
**Components to change:** `apps/api/src/app/agent/tools.py` or a new post-processing filter in the review pipeline.
**Innovation:** First application of production hallucination detection at per-comment granularity for PR review agents.

### 3. Detect-Repair-Verify for Suggestion Blocks (HIGH/HIGH/MED)
**Problem:** We generate `suggestion` code blocks for one-click commits. ComBench shows syntax fix rates far exceed semantic correctness rates — we may be posting syntactically plausible but semantically broken suggestions.
**Proposed solution:** After generating a suggestion, run a syntax/compile verify pass (AST parse + optional lint). Failed suggestions are either revised by the agent or converted to advisory comments without code blocks. Multi-language: Python, TypeScript, Go, Rust as initial targets.
**Components to change:** New `apps/api/src/app/agent/suggestion_verifier.py`, called from review finalization.
**Innovation:** Extends the PR review pipeline with an explicit "can this suggestion actually apply?" gate backed by empirical evidence of the syntax/semantic gap.

### 4. NL/PL Boundary Taint Tracking for Suggestions (HIGH/HIGH/HIGH)
**Problem:** Code suggested by the agent is derived from untrusted PR content. If an adversary embeds instructions in PR code/comments that shape the suggestion, the committed code becomes a trusted artifact from untrusted origin.
**Proposed solution:** Implement a lightweight taint-propagation tracker: mark all content from PR diffs as TAINTED. Any suggestion block whose generation relied on TAINTED content gets a `[agent-suggested: derived from untrusted diff]` disclosure in the review comment metadata. Optionally add a human-approval flag.
**Components to change:** `apps/api/src/app/agent/` (context construction), schema changes in `apps/api/src/app/db/models.py`
**Innovation:** First formalization of NL/PL boundary taint in code review agents, making the trust chain explicit.

### 5. Overcorrection Calibration Pass for Conformance Judgments (HIGH/MED/MED)
**Problem:** Recent empirical work shows LLMs systematically over-flag conformant code when asked to judge requirement conformance. This generates false-positive review noise and reduces developer trust.
**Proposed solution:** After the main review, run a calibration pass on each conformance finding: compare the flagged code against a small corpus of accepted conformant patterns (built from merged PRs that had no relevant comments). Use this to suppress over-correction candidates.
**Components to change:** `apps/api/src/app/agent/` (post-processing), new calibration data pipeline from merged PR history.
**Innovation:** Addresses a measured systematic bias using retrospective accept/reject signals from the repo itself.

### 6. Organic Repository Memory for Context-Appropriate Review (MED/HIGH/MED)
**Problem:** Our review comments may be contextually alien — correct in isolation but inappropriate given this specific project's conventions, patterns, or tech debt decisions.
**Proposed solution:** Maintain a lightweight per-installation repository memory (tech stack conventions, recurring patterns, team-specific style decisions extracted from past merged PRs). Inject this as a concise context prefix before generating review comments.
**Components to change:** New `apps/api/src/app/agent/repo_memory.py`, per-installation DB table.
**Innovation:** Adapts the "organic commit generation" paradigm to PR review, making agent feedback project-contextual rather than generic.

### 7. DDI Iteration Budget + Decay-Triggered Exploration Reset (HIGH/MED/LOW)
**Problem:** Our agent can run multiple review iterations. The Debugging Decay Index shows iterative LLM reasoning quality decays exponentially after 2-3 attempts.
**Proposed solution:** Add an iteration budget monitor to the ReAct loop with a configurable DDI threshold (default: 3 iterations). When the agent loops beyond the threshold without new material findings, trigger an exploration reset (fresh context window, different tool call strategy) rather than deepening the same path.
**Components to change:** `apps/api/src/app/agent/` (ReAct loop controller) — low-invasiveness change.
**Innovation:** First principled application of DDI decay metrics to bound review iteration cost.

### 8. 0-5 Severity Rubric Standardization (MED/MED/LOW)
**Problem:** We currently use a 4-tier severity (critical/high/medium/low). Empirical work shows 0-5 scale maximizes human-LLM agreement for judging.
**Proposed solution:** Change internal severity representation to 0-5 integer scale. Map to public severity tiers for display: 0-1 → advisory, 2-3 → medium, 4 → high, 5 → critical. Update the judge prompts and rubrics accordingly.
**Components to change:** `apps/api/src/app/agent/schemas.py`, rubric prompts, frontend severity display.
**Innovation:** Data-backed change to the most fundamental evaluation parameter in our judging pipeline.

### 9. LLM Judge Security Hardening via SoK Taxonomy (MED/HIGH/MED)
**Problem:** The SoK (Security in LLM-as-a-Judge) formalizes how judges can be attack targets — adversarial PR content can steer review scores/verdicts. Our judge is a direct attack surface.
**Proposed solution:** Apply SoK taxonomy to audit our judge LLM input pipeline: (1) add input guards for known judge-manipulation patterns; (2) separate the content-processing LLM from the scoring LLM (use different model calls for "what does this code do?" vs "what severity is this?"); (3) add a consistency check across multiple judge invocations.
**Components to change:** `apps/api/src/app/agent/` (judge calls), new judge guard layer.
**Innovation:** First systematic application of judge-specific security taxonomy to a production code review pipeline.

---

## Cross-Session Meta-Architecture Insights

### Today's Learning (Session 10)
**DUAL PIPELINE PATTERN confirmed:** Five sessions now independently converge on a dual-pass architecture:
- Pass 1: Specialized detection (security agent, hallucination guard, overcorrection detector)
- Pass 2: Verification/calibration (verify suggestion blocks, judge security, taint tracking)

This dual-pass structure is more robust than any single-model review. The key insight from today: *both passes must be grounded in the same diff*, and the grounding check (HalluJudge) should be the very first gate.

**SUPPLY CHAIN IS THE NEW INJECTION SURFACE:** Kill-Chain Canaries, MalSkills, NL/PL Taint, and Attesting LLM Pipelines all point to the same emerging threat: the attack is not just in the prompt, it's in the model weights, the skill registry, and the MCP tool store. This is a new category not well-represented in prior sessions.

**POTENTIAL PAPER HYPOTHESIS (strengthened, Session 10):**
Combining: IRT rubric discrimination + conformal prediction + APE failure mining + DDI decay bounds + HalluJudge grounding + kill-chain canary injection tracking + NL/PL taint tracking = a unified "trustworthy code review agent" framework. 7 sessions, 4 independent research lenses, consistent convergence. This is a novel combinatorial contribution not yet in literature.

---

## Zotero Status
- ZOTERO_API_KEY is set but was reported invalid (403) in previous runs. Papers saved to R2 only.

## Artiforge Status
- Still in ERROR state. Unavailable for agent orchestration.

## Model Availability
- User-requested models (GPT 5.5 Medium, Opus 4.7 High, Opus 4.6 High, Sonnet 4.6 High) are NOT available as Cursor Task subagent model slugs. Research performed with `composer-2-fast` agents.
