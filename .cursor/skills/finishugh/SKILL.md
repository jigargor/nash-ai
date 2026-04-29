---
name: finishugh
description: >-
  Like babysit: triage PR comments, resolve conflicts when clear, fix CI until
  checks are green—then merge each PR when status checks pass. Optionally, when
  the user explicitly requests it, run additional merges between named branches
  in order (e.g. develop into main after checks).
---
# Finishugh PR
Your job is the same as **babysit**—get the PR merge-ready—**and** merge when automation allows, plus any **user-requested** branch merges.

## Shared with babysit (always)

1. **Base branch**: Confirm the PR targets the branch the user intends (this repo’s default integration branch is `develop`). Retarget with `gh pr edit <n> --base <branch>` when the user asks.

2. **Comments**: Review every comment (including Bugbot). Fix only what you agree with; explain disagreement or uncertainty.

3. **Merge conflicts**: Sync with base; resolve only when intent is clearly the same—otherwise stop and ask.

4. **CI**: Fix issues with small scoped fixes, push, re-watch until **mergeable and all required checks green** and comments triaged.

## Merge the PR (default for this skill)

When the PR is **mergeable**, **required checks are success**, and there is **no unresolved review policy** blocking merge:

- Merge with `gh pr merge <number>` using the repository’s intended style: prefer the repo default (omit `--squash` / `--rebase` / `--merge` if unsure, or pass the one the user specified).
- If merge requires admin or bypass, stop and tell the user.
- After merge, confirm with `gh pr view <number> --json state` or the merge URL.

Wait for checks to finish before merging; do not merge on pending required checks.

## Extra merges (only if the user specifies)

**Do not** run follow-up branch merges unless the user **explicitly** names targets and order (examples: “then merge `develop` into `main`”, “merge everything to `release` once green”, “after that merge to `main` again when checks pass”).

When they do specify:

1. Treat their list as an **ordered pipeline** (step 1, then step 2, …).
2. For each step, use the mechanism that matches their wording: e.g. merge an **existing PR** with `gh pr merge`, or merge **branch A into B** by opening/merging the appropriate PR or following their exact branch names with `gh` (never force-push or rewrite history unless they explicitly ask).
3. After each merge that triggers CI, **wait until required checks on the relevant branch/PR are green** before the next step.
4. If a step is ambiguous (no PR exists, branch protection blocks you), stop and ask—do not guess destructive git operations.

## Multi-PR sessions

If the user is babysitting **multiple** PRs: repeat the babysit → green → **merge** cycle per PR unless they asked to merge only a subset—then follow their scope exactly.
