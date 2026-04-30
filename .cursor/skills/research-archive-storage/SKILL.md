---
name: research-archive-storage
description: Preserve LLM research runs across Slack, AutomationMemory, Zotero, and R2. Use for `/learn` runs that collect papers and `/save` requests that ask to store research artifacts.
---

# Research Archive Storage

## Purpose
Use this skill when a research automation collects papers or when a user asks to save, archive, store, sync, or recover research data.

The goal is to keep a canonical manifest from the research run, write it to every configured storage target, and clearly report partial success without inventing missing bibliographic records.

## Workflow
1. Identify the source research run:
   - Slack thread timestamp or channel digest.
   - Existing AutomationMemory file.
   - Local artifact or manifest produced by the research agent.
2. Locate or create a canonical manifest before attempting external writes. Include, when available:
   - DOI or stable identifier.
   - Title, authors, year, venue, URL.
   - Abstract or relevant excerpts.
   - Theme/category.
   - Recommendations or repo-specific implications.
   - Source query and retrieval date.
3. Validate storage configuration without printing secrets:
   - Zotero: `ZOTERO_API_KEY`, `ZOTERO_USER_ID`, `ZOTERO_LIBRARY_TYPE`, and `ZOTERO_LIBRARY_ID` when using a group library.
   - R2: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, and `R2_ENDPOINT_URL`.
4. Write the same manifest to each available target:
   - AutomationMemory as the fallback source of truth.
   - Zotero research collection when Zotero credentials are complete.
   - R2 research bucket when R2 credentials are complete.
5. If a target is unavailable, preserve the manifest locally or in AutomationMemory and explain exactly which non-secret variables or source records are missing.
6. Reply in Slack with:
   - What was saved.
   - Where it was saved.
   - What could not be saved and why.
   - Any next action needed from the user.

## Safety Rules
- Never print API keys, access keys, secret keys, tokens, or signed URLs.
- Do not fabricate DOIs, titles, authors, or paper counts from summaries.
- If Slack only contains a digest and not a paper manifest, save the digest as recoverable research context and state that a full corpus sync needs the original manifest or a rerun.
- Prefer structured JSON or Markdown manifests over free-form prose when creating new artifacts.

## Quality Bar
- A `/learn` run should leave behind enough structured data for `/save` to be idempotent.
- A `/save` run should be safe to repeat and should not duplicate Zotero/R2 records when stable identifiers are available.
- Partial archival is acceptable only if the response names the missing prerequisites.
