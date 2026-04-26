# Privacy and GDPR Readiness

## Data Processed

The review pipeline may process:

- repository metadata (owner/repo, PR number, commit SHA)
- PR diffs and selected file content used for review context
- generated findings, confidence, and evidence metadata
- model audit events (provider/model/stage/token usage/decision metadata)

## Purpose and Lawful Basis

- Purpose: automated code review quality and safety feedback.
- Suggested lawful basis: legitimate interests or contract performance, depending on customer agreements.

## Subprocessors

Production deployments should document enabled subprocessors, typically:

- GitHub (source control and PR data)
- LLM providers configured in environment (`anthropic`, `openai`, `gemini`)
- optional observability providers (Sentry, Langfuse)

## Data Minimization

- Send only review-relevant code context.
- Avoid transmitting secrets or credentials in prompts.
- Bound cross-model handoff to structured findings and minimal excerpts.

## Retention and Deletion

- Define an operational retention window for reviews and audit artifacts (for example 90 days).
- Provide per-installation deletion workflows that purge review and model-audit records.
- Ensure deletion jobs preserve referential integrity and tenant isolation.

## International Transfers

- Verify and maintain contractual safeguards (for example SCCs) with all active subprocessors.
- Keep transfer-impact records in deployment documentation.

## Data Subject Rights

Support export and deletion workflows at the tenant/account level, including:

- review findings
- model audit records
- OAuth-linked account data

## Cookies and Consent

- Current dashboard auth uses an essential httpOnly session cookie (`nash_session`) with `sameSite=lax`.
- Essential cookies used strictly for authentication/session security are generally exempt from opt-in consent in many jurisdictions.
- If you add analytics, marketing, A/B testing, or cross-site tracking cookies, implement a consent banner before setting those cookies.
- Publish a user-facing cookie notice that explains cookie purpose, lifetime, and how users can revoke optional consent.
