# AutomationMemory Index

## LLM Research Sessions

| Date | File | Papers | Zotero Collection | R2 |
|------|------|--------|-------------------|----|
| 2026-04-29 | llm-research-2026-04-29.md | ~35 papers | llm-research (legacy) | ❌ Missing credentials |
| 2026-04-30 | llm-research-2026-04-30.md | 15 papers | llm-research | ❌ Missing R2_ACCOUNT_ID, R2_BUCKET_NAME, R2_ENDPOINT_URL |
| 2026-05-02 | llm-research-2026-05-02.md | 40 papers | LLM Research 2026-05-02 | ❌ InvalidRequest: revoked/wrong-scope token |

## R2 Credentials Needed

To enable R2 sync, add these to Cursor Cloud → Secrets:
- `R2_ACCOUNT_ID` — Cloudflare account ID (currently missing)
- `R2_BUCKET_NAME` — bucket name (currently missing)  
- `R2_ACCESS_KEY_ID` — currently set but returning InvalidRequest (regenerate in Cloudflare dashboard)
- `R2_SECRET_ACCESS_KEY` — currently set
- `R2_ENDPOINT_URL` — currently set
