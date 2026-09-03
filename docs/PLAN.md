# Nash AI — Phased Plan

The historical private build plan lives in `private_docs/plan.md` (gitignored).

**Current overhaul:** see [`ARCHITECTURE.md`](../ARCHITECTURE.md) and [`docs/STATUS.json`](STATUS.json).

Wave order (dependency):

1. Evals harness + telemetry schema + model migration + pipeline seam
2. Ingestion, context-packaging, agent-core, infra resilience
3. Validation, prompts (harness-gated), delivery, frontend
4. Production outcome tracking end-to-end

Progress, scores, budgets, and open issues are persisted in `docs/STATUS.json`. Nothing gets a score until it has run through the harness.
