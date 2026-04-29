---
name: fastr-pr
description: >-
  Compact PR title and body, small-diff summary, readiness checklist, key risks.
  Use for PR open/update flows and background automation that need minimal
  copy-paste PR text. Same workflow as fast-pr with strict brevity.
---

# fastr-pr (compact fast PR)

Apply the **fast-pr** skill workflow in full: see [fast-pr/SKILL.md](../fast-pr/SKILL.md).

**Emphasis for this skill name:** default outputs must stay **tight**—aim **under ~40 lines** total, bullets over prose, no optional sections unless the diff demands them.

When another artifact (for example **pr-closer**) asks for “title and body,” produce:

1. One-line **title** (imperative, ≤72 characters).
2. **Body** markdown: short summary, test plan, checklist—suitable to append policy footers (for example `[skip-nash-review]`) without re-editing structure.
