---
name: fast-pr
description: >-
  Drafts short PR titles and bodies, summarizes small diffs, merge-readiness
  checklist, and obvious risks for the Nash AI monorepo. Use when opening or
  updating a pull request, when the user wants a quick PR summary, or when
  pairing with automation that needs copy-paste PR text.
---

# Fast PR

Lightweight PR artifacts: **speed and clarity** over exhaustive review. Defer deep review to a dedicated pass.

## When to use

1. If the user gives a branch or task, infer scope from minimal **git context** when available (`git status`, `git diff`, `git log -1`)—only what you need to summarize.
2. If the request is vague (“open a PR”), ask for **branch name** or **what changed** in one line, then proceed.

## Output format (default, markdown copy-paste)

Unless the user asks otherwise:

1. **Suggested PR title** (imperative, ≤72 characters)
2. **Summary** (3–6 bullets: what, why, user impact)
3. **Scope / non-goals** (1–2 lines only if unclear)
4. **Risk and rollout** (migrations, auth, webhooks, queues—only if touched)
5. **Test plan** (commands or manual steps that match the diff)
6. **Checklist** (CI, types, secrets, breaking changes)

Keep the whole response **under ~40 lines** unless the user explicitly asks for depth.

## Constraints

- Do **not** paste or guess secrets, tokens, or environment values.
- If the change touches **security-sensitive** paths (auth, webhooks, cookies, DB RLS), flag that in one line.
- Prefer **named files and routes** when referencing code; avoid dumping large diffs.

## Escalation

If the work needs full design review, performance work, or incident-style debugging, say so in one sentence and suggest the next step—do not imply this pass is exhaustive.
