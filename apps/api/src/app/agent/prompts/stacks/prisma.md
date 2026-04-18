Prisma-specific rules:
- Prisma schema files define model intent; generated client files should not be hand-edited.
- Distinguish nullable database fields from optional TypeScript properties carefully.
- Suggest migration/backfill patterns for schema changes that can affect existing rows.
