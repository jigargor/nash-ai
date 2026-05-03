# LLM Research Memory — May 2, 2026

**Retrieval date:** 2026-05-02  
**Session:** Nash AI LLM Research Daily Brief | May 2, 2026  
**Papers ingested:** 40 new papers across 5 domains  
**Zotero collection:** LLM Research 2026-05-02 (already written by research agent)  
**R2 status:** Sync failed — `InvalidRequest: Please use AWS4-HMAC-SHA256`. R2 token appears revoked or scoped to wrong bucket. `R2_ACCOUNT_ID` and `R2_BUCKET_NAME` are also not set in this environment.

---

## Domains Covered

1. Code quality / diff prompting
2. Prompt eval / rubric rewards
3. Inference efficiency
4. Prompt injection / security
5. Multi-agent architectures

---

## Key Papers Referenced in Slack Digest

These were cited by name in the ranked proposals; full DOI manifest was not emitted to Slack by the research subagents.

| # | Short ID | Domain | Nash AI Proposal |
|---|----------|--------|-----------------|
| 1 | Firewall (2510.05244) | Prompt injection | Tool-Output Firewall Sanitizer |
| 2 | SIC (2510.21057) | Prompt injection | `.codereview.yml` base-branch-only loading |
| 3 | RRM (2510.07774) | Rubric rewards | Rubric-Verified Critic pass |
| 4 | Rating Roulette (2510.27106) | Eval / scoring | Rubric-Verified Critic pass |
| 5 | ContextCRBench (2511.07017) | Code review bench | Issue-context injection from GitHub issues |
| 6 | BATS (2511.17006) | Inference efficiency | Budget-Aware Tool Dispatch |
| 7 | RevAgent (2511.00517) | Multi-agent | Role-specialized Multi-Commentator agents |
| 8 | MAESTRO (2511.06134) | Multi-agent | Role-specialized Multi-Commentator agents |
| 9 | COMPASS (2510.08790) | Context management | Cross-Chunk Context Manager |
| 10 | CompressionAttack (2510.22963) | Adversarial prompting | Prompt-compaction adversarial hardening |
| 11 | RLAC (2511.01758) | RL / feedback | Self-improving reject-signal loop |
| 12 | ALIGNEVAL (2511.20604) | Eval | Self-improving reject-signal loop |
| 13 | CommandSans (2510.08829) | Prompt injection | Tool-Output Firewall Sanitizer |

---

## Ranked Improvement Proposals

Sorted by Impact ↓, Innovation ↓, Complexity ↑:

| # | Proposal | Impact | Innovation | Complexity |
|---|----------|--------|------------|------------|
| 1 | `.codereview.yml` base-branch-only + allowlist injection fix | Critical | Medium | Low |
| 2 | Tool-Output Firewall (Sanitizer) on tool results | High | Medium | Low |
| 3 | Rubric-Verified Critic pass before posting comments | High | High | Medium |
| 4 | Issue-context injection from linked GitHub issues | High | Low | Low |
| 5 | Budget-Aware Tool Dispatch in ReAct loop | High | Medium | Low |
| 6 | Role-specialized Multi-Commentator agents (fan-out) | Medium | High | High |
| 7 | COMPASS-style Cross-Chunk Context Manager | Medium | High | Medium |
| 8 | Prompt-compaction adversarial hardening | Medium | Medium | Low |
| 9 | Self-improving reject-signal feedback loop | High | High | Very High |

---

## Implementation Roadmap (from cross-agent synthesis)

1. **First:** Fix `.codereview.yml` base-branch loading + Tool-Output Sanitizer (security prerequisite)
2. **Second:** Budget tracker + rubric verifier (quality wins with existing architecture)
3. **Third:** Issue-context injection (low effort, high return)
4. **Later:** Multi-agent fan-out + context manager (architecturally invasive)
5. **Research horizon:** Reject-signal self-improvement loop

---

## Key Cross-Cutting Insight

> "The injection surface, the context window, and the evaluation reliability problem are the same problem seen from three angles."

An injection-hardened context pipeline (firewall → sanitizer → delimiter) is also what enables rubric-based evaluation to be reliable. Budget-aware context selection reduces context noise which reduces both hallucination and injection exposure. Multi-agent architecture only becomes safe when the sanitization layer is in place.

---

## Storage Status

| Target | Status | Notes |
|--------|--------|-------|
| AutomationMemory | ✅ Saved | This file |
| Zotero | ✅ Written by research agent | Collection: `LLM Research 2026-05-02` |
| R2 | ❌ Failed | `InvalidRequest: AWS4-HMAC-SHA256` — token revoked or wrong bucket scope. Missing: `R2_ACCOUNT_ID`, `R2_BUCKET_NAME` |

---

## Source Queries (from Apr 30 session — carried forward)

- Code quality + LLM review agents (Nov 2025 – May 2026)
- Prompt injection defenses for LLM agents
- Multi-agent architectures for SE tasks
- Rubric reward models / LLM evaluation reliability
- Budget-aware inference / tool dispatch
