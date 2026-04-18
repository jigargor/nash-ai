## Examples of BAD findings (do not emit these)

BAD: Flagging a TypeScript type mismatch between generated Supabase types and
manual types. Generated types are authoritative; do not suggest editing them.

BAD: Line 158 shows `<div className="space-y-2">` and you flag a race condition
in state management. The line doesn't contain state code. If the issue is on a
different line, target THAT line, not this one.

BAD: Marking a missing NOT NULL constraint as `critical`. A default value handles
the NULL case for new inserts; existing NULL rows would need backfill regardless.
This is `medium` at most.

## Examples of GOOD findings

GOOD: Line 45 has `JSON.parse(userInput)` with no try/catch. This will throw on
malformed input. Suggestion: wrap in try/catch with a default value.

GOOD: Line 112 calls `await fetch(url)` with no timeout. In production this can
hang indefinitely. Suggestion: use AbortController with 10s timeout.
