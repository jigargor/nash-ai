---
name: fastr-pr
description: >-
  Compact PR title and body, small-diff summary, readiness checklist, key risks.
  Use for PR open/update flows and background automation that need minimal
  copy-paste PR text. Same workflow as fast-pr with strict brevity. Bodies must
  be grounded in git log/stat for the actual base/head—no generic integration filler.
---

# fastr-pr (compact fast PR)

Apply the **fast-pr** skill workflow in full: see [fast-pr/SKILL.md](../fast-pr/SKILL.md).

**Emphasis for this skill name:** default outputs must stay **tight**—aim **under ~40 lines** total, bullets over prose, no optional sections unless the diff demands them.

When another artifact (for example **pr-closer**) asks for “title and body,” produce:

1. One-line **title** (imperative, ≤72 characters).
2. **Body** markdown: short summary, test plan, checklist—suitable to append policy footers (for example `[skip-nash-review]`) without re-editing structure.

## Grounding (required when base and head are known or implied)

Do **not** write summary bullets from memory or from vague “integration merge” templates. Before title/body, derive scope from the repo (agent may run these locally):

1. `git fetch origin <base> <head>` when remotes may be stale (or `git fetch origin` if unsure).
2. `git log --oneline <base>..<head>` — cap ~30–50 lines; read **commit subjects** for themes (`fix(api):`, `chore(deps):`, merge commits, etc.).
3. `git diff --stat <base>...<head>` — note **directories**, large files, and insert/delete scale (`N files changed`).

Use **merge-base** syntax (`base...head`) for the stat so merge commits compare correctly to the PR diff.

From that evidence:

- **Summary**: 3–8 bullets naming **real areas** (e.g. `apps/api/agent`, `apps/web` review UI, `.github/workflows`, lockfiles, `.cursor` rules/skills). For large merges, **group by theme**, not one bullet per commit.
- **Risk and rollout**: only if the log/stat shows migrations, auth/API routes, webhooks, queues, or risky dep pins—**one line each**, tied to what you saw.
- **Test plan**: commands or checks that **match** touched apps (e.g. `pytest` paths, `pnpm`/CI job names from workflow or package scripts)—not generic “smoke the app” unless nothing specific surfaced.

## Anti-patterns (reject in your own output)

- Filler like “latest `develop` work,” “validated on `develop`,” “routine integration,” or “no feature-specific narrative” **without** substituting concrete themes from `git log` / `git diff --stat`.
- Checklist items that ignore what changed (e.g. only “CI green”) when the stat shows API + web + workflows—tie checklist to **those** surfaces.
- Guessing release impact: if unclear, one honest line (“large merge; spot-check review UI and agent API”) beats invented user-impact bullets.

## Windows note

In PowerShell use `;` instead of `&&`, and `Select-Object -First N` instead of `head -N` when needed.
