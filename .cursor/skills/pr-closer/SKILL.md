---
name: pr-closer
description: >-
  Closes or clears open PRs by pattern (branch head names), merges when checks
  are green, fixes failures in Agent mode until green, updates PR title/body
  using fastr-pr, and optionally appends [skip-nash-review] to descriptions.
  Use when the user asks to sweep dependabot/cursor branches, finish an
  integration branch, or merge/clean PRs between two named branches; ask
  clarifying questions when scope is ambiguous.
---

# PR closer

Orchestrates **many open PRs**: discover, optionally refresh title/body, skip-review tagging, **merge if all required checks pass**, otherwise **fix in full Agent mode** (write access, tools, push) until mergeable or blocked.

## Defaults (unless the user overrides)

- **Base branch**: Pre-v1 default base is `main`—confirm if the user meant another base.
- **Description footer**: When updating a PR body, append **`[skip-nash-review]`** on its own line at the end **unless** the user says not to (or specifies different footer text).
- **Title/body refresh**: Use the **fastr-pr** skill (see [.cursor/skills/fastr-pr/SKILL.md](../fastr-pr/SKILL.md)) for suggested title and body; merge user intent if they already provided copy.
- **Merge**: Only when the PR is mergeable and **required checks are success**—same discipline as **finishugh** / **babysit** (wait for pending checks; no merge on red).
- **If checks fail or reviews block**: use **Agent mode** (not Ask, not readonly): small scoped fixes, push, re-poll checks; repeat until green or you hit an ambiguity/blocker.

## How the user may specify scope

### A) Pattern groups on head branch names

Examples: all heads matching `dependabot/*`, `cursor/*`, a regex, or a list of prefixes.

1. Resolve patterns to a candidate set with `gh pr list` (JSON filters) or equivalent.
2. Process each PR in the set.

### B) “Between two branches” or “finish this line of work”

Interpretations vary—**ask** if any of these are unclear:

- **PR base/head pair**: “All open PRs from **`feature/a`** into **`main`**” (explicit base + head).
- **Integration finish**: “Everything targeting **`release/1.2`**” or “all PRs with base **`main`** whose head matches **`cursor/**`**.”
- **Prefix/suffix**: “Branches that **start with** `dependabot`” vs “**contain** `cursor`.”

If the user says “between `main` and `develop`,” clarify whether they mean PRs **base `main` head `develop`**, the opposite, **both directions**, or **all PRs in a compare range** (not always representable as a single `gh` query—prefer explicit base/head).

### C) Explicit PR numbers

If they list numbers, restrict to that set only.

### D) Explicit head-branch allowlist

When another workflow (for example **code-sesh**) passes an **exact list** of `headRefName` values (such as `bugfix/foo`, `bugfix/bar`), process **only** those heads into the named base—do not expand to pattern sweeps or unrelated PRs.

## Clarifying questions (use when anything is ambiguous)

Ask before bulk merges when:

- **Merge method** (merge commit vs squash vs rebase) is unspecified and repo policy matters.
- **Which checks count as “all passed”** (required vs optional) is unclear.
- **Draft PRs** should be included or skipped.
- **Branch protection / admin merge** might apply—surface early.
- **Destructive git** (force-push, history rewrite) would be needed—they must opt in explicitly.

## Per-PR loop

1. `gh pr view <n> --json ...` (state, mergeable, statusCheckRollup, baseRefName, headRefName, isDraft).
2. Skip drafts if the user asked to skip drafts; if unclear, ask once for the session.
3. If refreshing metadata: run **fastr-pr** on the diff scope for that PR; `gh pr edit` title/body; ensure **`[skip-nash-review]`** footer policy per user.
4. If **mergeable and required checks success**: `gh pr merge <n>` (use merge style the user specified, else repo default / omit flags per **finishugh** guidance).
5. Else: triage failures, fix with code changes, push, wait for checks—**babysit**-style until mergeable or blocked.

## Escalation

If merge requires disallowed bypass, permissions, or product decisions, stop with a short status per PR and what the user must do manually.
