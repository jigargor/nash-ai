# Artiforge Review Capability Wiring

This document explains how to wire MCPs, subagents, skills, rules, and hooks for the Artiforge PR/repo review orchestration instance.

## Baseline Config

- Primary instance: `.cursor/templates/artiforge-pr-repo-review.yaml`
- Template baseline: `.cursor/templates/big-boss-team.yaml`

## Phase 1 (No Brainer) Wiring

- **MCPs**
  - `user-github` for PR metadata, checks, comments, and changed files.
  - CI MCP (if present) for failing-check evidence.
- **Subagents**
  - `explore` for read-only codebase mapping.
  - `shell` for deterministic git/test/lint evidence.
- **Skills**
  - PR summarizer + risk triage.
  - CI-failure triage.
- **Rules**
  - `.cursor/rules/80-findings-first-review-output.mdc`
- **Hooks**
  - `.cursor/hooks/build_context_pack.py` via `postToolUse`
  - `.cursor/hooks/validate_review_payload.py` via `beforeMCPExecution`

## Phase 2 (Quite Useful) Wiring

- **MCPs**
  - Observability MCPs: Sentry/Datadog (if installed).
  - Work-tracking MCPs: Jira/Linear (if installed).
- **Subagents**
  - Multi-agent compare/synthesize pass.
  - Browser subagent for UI regressions.
- **Skills**
  - Security review skillpack.
  - Migration and DB policy skillpack.
- **Rules**
  - `.cursor/rules/81-path-aware-review-strictness.mdc`

## Phase 3 (Scoring and Governance) Wiring

- **Hooks**
  - `.cursor/hooks/score_test_gap.py` for missing-test pressure.
  - `.cursor/hooks/score_risk.py` for sensitive-path risk escalation.
- **Operations**
  - Turn on `rollout_flags.phase3_scoring` only after collecting enough baseline telemetry from Phase 1 and Phase 2 runs.
  - Keep format-gate hook fail-closed; keep scoring hooks fail-open to avoid workflow deadlocks.

## Dependency Order

1. Contracts and output schema enforcement
2. Core MCP + worker + baseline skills
3. Enrichment MCPs + advanced routing
4. Scoring automation and threshold tuning

## Validation Checklist

- Reviews include severity, evidence citation, and suggested fix.
- Risk findings appear before style findings.
- Context pack captures changed files, checks, and commit context.
- Sensitive file touches increase strictness and escalate required proof.
- Test-gap and risk scores are visible in additional context for synthesis.
