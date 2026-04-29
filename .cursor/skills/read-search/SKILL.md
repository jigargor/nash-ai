---
name: read-search
description: Researches implementation best practices using current chat context and the user's explicit prompt, then proposes a concrete default. Use when the user asks to "research", "read-search", "best practice", or requests a recommended config value grounded in docs.
---

# Read Search

## Purpose
Use this skill to turn a user prompt into a concrete recommendation backed by current docs and repository context.

## Workflow
1. Restate the exact decision to make from the user's prompt.
2. Read the most relevant local files already implicated by the chat (route/page/module being changed).
3. Research current official docs and one secondary source if needed.
4. Compare options in one short list:
   - option
   - tradeoff
   - fit for this repo
5. Pick a default and implement it immediately unless the user asked for analysis only.

## Quality bar
- Prefer official framework docs first.
- Keep recommendations specific to the touched route or feature.
- If the user explicitly accepts uncached behavior, treat `0` revalidation as the default candidate and validate against docs before applying.
- Do not invent unsupported config flags or stale APIs.

## Output format
- Decision
- Why
- Applied change
- Quick verification step
