# Tier 4 branch decisions (branch cleanup)

Recorded after the branch cleanup pass so retained branches have explicit rationale.

## `feat/langgraph-review-chain-poc`

- **Status:** Kept on `origin` as a long-lived POC/reference branch.
- **Why not merged:** Work predates the pre-feature roadmap foundations (quality model, LLM observer, reproducible evals, labeling, calibration). Merging now would layer feature complexity before those gates are stable.
- **Next steps:** Rebase or re-apply against current `develop` when LangGraph / shadow-benchmark work is scheduled; expect conflict resolution and re-validation of the review pipeline.

## `chaos/research-interaction-flow-0f35`

- **Status:** **Resolved** — commit `93c05f8` (`docs: add research archive storage skill`) was **cherry-picked** onto `develop` as `78b34ff`.
- **Remote branch:** Deleted after cherry-pick so the skill lives only on `develop` (no duplicate branch).

## Related

- **develop → main:** `main` may lag `develop`; open a dedicated integration PR when ready to ship.
