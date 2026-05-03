---
name: babysit
description: >-
  Keep a PR merge-ready by triaging comments, resolving clear conflicts, and
  fixing CI in a loop. In this repo, open PRs normally target main unless
  the user says otherwise.
---
# Babysit PR
Your job is to get this PR to a merge-ready state.

Check PR status, comments, and latest CI and resolve any issues until the PR is ready to merge.

1. **Base branch**: Confirm the PR targets the branch the user intends (pre-v1 default is `main`). If the user asked for a different base, retarget with `gh pr edit <n> --base <branch>` when appropriate.

2. **Comments**: Review every comment (including Bugbot) before acting. Fix only comments you agree with; explain when you disagree or are unsure.

3. **Merge conflicts**: When there are conflicts, sync with base branch. Resolve merge conflicts only when intent is clearly the same, otherwise stop and ask for clarification.

4. **CI**: Fix CI issues that come up with small scoped fixes. Push them and re-watch CI until mergeable + green + comments triaged.

Do **not** merge the PR unless the user explicitly asks you to merge (use the `finishugh` skill for auto-merge after green checks).
