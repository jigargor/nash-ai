This is a Next.js project. Apply these rules:
- App Router uses Server Components by default; "use client" is deliberate
- Do NOT flag missing 'use client' unless you've verified the component uses hooks/events
- Server Actions should be in files with "use server" directive
- `cookies()` and `headers()` are only available in Server Components/Actions
