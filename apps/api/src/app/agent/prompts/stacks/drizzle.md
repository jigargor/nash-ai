Drizzle-specific rules:
- Distinguish schema declarations from runtime query code when reasoning about safety.
- Missing constraints can be medium/high depending on usage; reserve critical for direct data loss/security risk.
- Validate migration assumptions against defaults/backfills before flagging strictness issues.
