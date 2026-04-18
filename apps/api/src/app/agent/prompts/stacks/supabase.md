Supabase-specific rules:
- Database types in `lib/supabase/types.ts` or `types/supabase.ts` are usually GENERATED
  from the schema. Do NOT suggest hand-editing them — suggest regenerating with
  `supabase gen types typescript --local` instead.
- RLS policies in migrations matter. Flag missing RLS on new tables.
- The Row/Insert/Update type distinction is intentional, not a bug.
