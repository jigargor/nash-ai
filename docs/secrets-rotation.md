# Secrets rotation runbook

This document lists **where secrets live** for this monorepo, how to **rotate** them safely, and how **object storage** fits in (Cloudflare R2 vs AWS).

**Rules:** never commit real secrets; never paste secret values into GitHub issues or chat logs; rotate from the provider’s UI or a password manager; record *that* a rotation happened (ticket + date), not the value.

---

## 1. Where secrets are stored

| Area | Typical use | Notes |
|------|-------------|--------|
| **GitHub** (repository or org **Actions secrets**) | CI: GitHub App fields, optional real PEM for tests, LLM key for optional DeepEval | Names used by workflows: `APP_ID`, `APP_WEBHOOK_SECRET`, `APP_CLIENT_ID`, `APP_CLIENT_SECRET`, `APP_PRIVATE_KEY_PEM`, `ANTHROPIC_API_KEY`. See `.github/workflows/`. |
| **GitHub App + OAuth App** (GitHub **Settings UI**) | Webhook HMAC, installation JWT signing, user login | Not the same as Actions secrets—you edit the **app** in GitHub, then mirror values into Railway/Vercel/Actions. |
| **Railway** | API service + **separate** ARQ worker: DB, Redis, GitHub App PEM, Fernet, LLM keys, CORS, admin keys, optional R2/Sentry/Langfuse | **API and worker must stay in sync** for anything the worker uses (GitHub PEM, `DATABASE_URL`, `REDIS_URL`, `FERNET_KEY`, LLM keys, R2, etc.). |
| **Vercel** | Next.js **server** env: OAuth, session signing, BFF `API_URL` + `API_ACCESS_KEY`, optional Upstash, JWT signing if set on web | See `apps/web/.env.example`. Prefer **Environment** scoping (Production / Preview). |
| **Cloudflare R2** (optional) | S3-compatible credentials for snapshot archive | `R2_*` vars on Railway only today (see repo-root `.env.example`). Rotate via Cloudflare **API Tokens** or **R2 S3 API** keys. |
| **Provider dashboards** | Anthropic / OpenAI / Google AI, Sentry, Langfuse, Upstash | Keys created and revoked in each vendor’s console. |

Local development: copy `.env.example` and `apps/web/.env.example` into ignored `.env` / `.env.local` files—**not** a rotation surface for production.

---

## 2. Full inventory (by variable)

Names below match **pydantic / Next** env unless noted. Railway/Vercel dashboards may show them in UPPER_SNAKE_CASE.

### 2.1 GitHub App (backend + worker; GitHub UI + Actions)

| Variable | Rotate in | Procedure summary |
|----------|-----------|-------------------|
| `GITHUB_APP_ID` | GitHub only if you replace the app | Usually immutable; new app ⇒ new installs and new ID everywhere. |
| `GITHUB_WEBHOOK_SECRET` | GitHub App settings + Railway (both services) + GitHub `APP_WEBHOOK_SECRET` if CI uses it | Single active value: generate new secret, update **all** receivers, then set the same value in GitHub’s webhook config. Short mismatch window ⇒ failed webhook deliveries (401). |
| `APP_PRIVATE_KEY_PEM` / `APP_PRIVATE_KEY_PEM_PATH` | GitHub App → add new key + Railway API + worker (+ optional `APP_PRIVATE_KEY_PEM` in Actions) | Add new PEM in GitHub, deploy new PEM everywhere, smoke-test GitHub API, **then** delete the old key in GitHub. |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | OAuth App on GitHub + Railway + Vercel | GitHub often allows **overlapping** client secrets: add new, deploy, verify login, revoke old. |

### 2.2 Railway (API + worker)

Scope vars by service (least privilege). The authoritative matrix lives in `docs/secret-env-matrix.json`.

- **Both API + worker (required):** `DATABASE_URL`, `REDIS_URL`, `FERNET_KEY`, `ENVIRONMENT`, `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, `APP_PRIVATE_KEY_PEM`.
- **API-only (required):** `API_ACCESS_KEY`, `DASHBOARD_USER_JWT_SECRET`, `DASHBOARD_USER_JWT_AUDIENCE`, `DASHBOARD_USER_JWT_ISSUER`, `ADMIN_RETRY_API_KEY`, `WEB_APP_URL`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`.
- **Worker optional (only if used by worker code paths):** `ADMIN_RETRY_API_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`.
- **Optional on both when enabled:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `SENTRY_DSN`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `R2_ENDPOINT_URL`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_REGION`, `R2_SNAPSHOT_PREFIX`, `ENABLE_REVIEWS`, rate/budget knobs.

**`API_ACCESS_KEY`:** must match Vercel `API_ACCESS_KEY` (BFF sends `X-Api-Key`). Rotate both in the same change window.

### 2.3 Vercel (Next.js server / BFF)

From `apps/web/.env.example` and code under `apps/web/src/`:

| Variable | Purpose |
|----------|---------|
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | OAuth login routes |
| `AUTH_SESSION_SECRET` | Cookie session signing (`src/lib/auth/session.ts`) |
| `API_URL` | Backend base URL for server-side proxy and callback |
| `API_ACCESS_KEY` | Must match Railway `API_ACCESS_KEY` |
| `DASHBOARD_USER_JWT_SECRET` (and audience/issuer if overridden) | JWT minted for API (`src/lib/auth/dashboard-token.ts`)—**must match** API if you set them on web |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Optional (`src/proxy.ts`)—rotate in Upstash, then Vercel |

**Public env:** `NEXT_PUBLIC_*` is not for secrets; do not put API keys there.

### 2.4 GitHub Actions

- **Quality / DB security workflows:** `APP_ID`, `APP_WEBHOOK_SECRET`, `APP_CLIENT_ID`, `APP_CLIENT_SECRET`, optional `APP_PRIVATE_KEY_PEM`. CI also pins a **non-secret** test `FERNET_KEY` in YAML for tests only—do not confuse with production `FERNET_KEY` on Railway.
- **DeepEval (optional):** `ANTHROPIC_API_KEY`.

After changing Actions secrets, trigger a workflow (e.g. push to a test branch) to confirm.

---

## 3. High-risk rotations (plan extra steps)

### 3.1 `FERNET_KEY`

Used to encrypt stored user OAuth tokens. **Changing the key without a migration** breaks decryption of existing rows.

**Options:**

1. **Operational:** schedule maintenance, accept forced re-login: backup DB, rotate key, clear or migrate `users.token_enc` per your policy, notify users.
2. **Proper:** dual-key period—decrypt with old OR new, re-encrypt with new—or a one-off script run against the DB. Document in the same ticket as the rotation.

### 3.2 `DASHBOARD_USER_JWT_SECRET` / `AUTH_SESSION_SECRET`

Rotating invalidates **existing sessions** (JWT and/or session cookies). Prefer off-peak; deploy API + web with the same new JWT secret if both participate in signing/verification.

### 3.3 `DATABASE_URL` / Postgres password

Railway (or host) password rotation: create new DB user/password or rotate in provider UI, update `DATABASE_URL` on **both** API and worker, restart, verify migrations/health, then revoke old credentials.

---

## 4. Suggested order (one coordinated change)

When rotating multiple items in one window:

1. **OAuth client secret** (overlap supported on GitHub).
2. **GitHub App private key** (add → deploy → verify → remove old key).
3. **Webhook secret** (tight coordination—GitHub + Railway + Actions).
4. **BFF bridge:** `API_ACCESS_KEY` on Railway **and** Vercel together.
5. **Session / JWT** secrets if you accept logout impact.
6. **LLM / Sentry / Langfuse / Upstash** keys at the vendor, then env vars.
7. **`FERNET_KEY`** only with an explicit DB/user-token plan.

---

## 5. Verification checklist

After any production rotation:

- [ ] GitHub → App → **Recent deliveries** for the webhook: success.
- [ ] Dashboard: OAuth login and a protected page load.
- [ ] API: health or a minimal authenticated route; worker processing a queued job.
- [ ] Vercel: preview (if used) has correct env scope or inherited secrets.
- [ ] CI: a PR that hits `quality-gates` still passes (if Actions secrets changed).

---

## 6. Object storage: AWS S3 vs Cloudflare R2 (this repo)

**Today’s codebase** documents **Cloudflare R2** for optional snapshot archive (`R2_*` variables in `.env.example`). There is **no** first-class AWS S3 configuration in the env templates—R2 is S3-compatible, so the app expects **S3 API semantics** against an R2 endpoint, not an AWS account per se.

| Topic | R2 (as wired here) | AWS S3 |
|--------|-------------------|--------|
| **Fit** | Already named and optional in repo; keys scoped to R2 buckets | Would require new env names or adapter config and AWS IAM design |
| **Cost / ops** | Generally **simpler and cheaper** for write-heavy archive + **no egress fees** to the Internet from R2’s pricing model (confirm current Cloudflare pricing). AWS S3 charges storage + requests + **egress**, and IAM is broader attack surface. | More features (VPC endpoints, Object Lock, cross-region replication)—worth it if you are already all-in on AWS compliance/networking. |
| **Recommendation** | **Prefer R2** for this project’s optional snapshot archive unless you have a hard requirement (existing AWS org, compliance boundary, unified AWS logging). | Choose AWS if those requirements dominate; expect a small code/config addition to treat `AWS_*` or a custom endpoint explicitly. |

**Rotation (R2):** in Cloudflare, rotate **S3 API credentials** (access key + secret) used for `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY`; update Railway API + worker; run a quick read/write test path if you have archive jobs enabled; revoke old keys.

---

## 7. Credential incident record

| Date | Incident | Resolution |
|------|----------|------------|
| 2026-04-26 | Real `GITHUB_CLIENT_ID` (`Ov23liZAOcxLLZxEJ904`), `GITHUB_CLIENT_SECRET`, and `AUTH_SESSION_SECRET` were committed to `apps/web/.env.example` in git history (commits `22e87d6`, `cde3c35`). | Credentials rotated 2026-04-29. File corrected in-tree. `docs/rotation-log.json` seeded with rotation dates. Gitleaks CI scan and weekly reminder added (see §8). |

The revoked values are allowlisted in `.gitleaks.toml` under `docs/` so the scanner does not re-alert on this historical record.

---

## 8. Automated enforcement

Three artefacts implement the rotation policy without manual tracking:

### 8.1 Secret scan (`.github/workflows/secret-scan.yml`)

Runs on every push to `main`/`develop` and on every pull request using **gitleaks**.

- **On PR:** scans only the new commits in the diff — fast, zero false positives from old history.
- **On push:** full-depth checkout; scans all pushed commits.
- Results upload as SARIF to the **Security → Code scanning** tab.
- Configuration lives in `.gitleaks.toml`, which allowlists:
  - CI-only test credentials hard-coded in workflow YAML (e.g. the test `FERNET_KEY`).
  - Placeholder values in `.env.example` files.
  - The revoked credentials documented in this runbook.

If the scan fails on a PR, the merge is blocked until the secret is removed from the branch history (use `git rebase -i` / `git filter-repo`).

### 8.2 Rotation log (`docs/rotation-log.json`)

Machine-readable registry: one entry per secret group with:

| Field | Meaning |
|-------|---------|
| `name` | Human-readable secret name (matches the env var) |
| `platform` | Where the value lives (Railway, Vercel, GitHub Actions, etc.) |
| `last_rotated` | ISO 8601 date of the most recent rotation |
| `max_age_days` | Policy lifetime before rotation is required |
| `rotation_guide` | Anchor link into this runbook |

**Maintenance rule:** after every rotation, update `last_rotated` in `rotation-log.json` and push to `main`. This is the single source of truth for staleness.

### 8.3 Rotation reminder (`.github/workflows/secret-rotation-reminder.yml`)

Runs every **Monday at 09:00 UTC** (and on `workflow_dispatch`).

- Reads `docs/rotation-log.json`.
- For each secret, computes `age = today − last_rotated`.
- **Overdue** (`age ≥ max_age_days`): opens (or updates) a GitHub issue labelled `secret-rotation,security` with a per-secret table and direct links to rotation procedures.
- **Due within 14 days**: included in the same issue as an early-warning section.
- If a `secret-rotation` issue is already open, the workflow updates its body rather than opening a duplicate.
- Closes itself: once `rotation-log.json` is updated and all secrets are within their window, the next Monday run finds nothing overdue and produces no issue.

### 8.4 Developer pre-commit setup (optional but recommended)

Install gitleaks locally to catch secrets before they reach CI:

```bash
# macOS
brew install gitleaks

# Linux (replace version/arch as needed)
curl -sSfL https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_linux_x64.tar.gz | tar xz
sudo mv gitleaks /usr/local/bin/
```

Add a pre-commit hook:

```bash
# .git/hooks/pre-commit  (chmod +x)
#!/usr/bin/env bash
gitleaks protect --staged --config .gitleaks.toml
```

Or with Husky (if you add it to the root `package.json`):

```bash
pnpm add -wD husky
pnpm exec husky init
echo 'gitleaks protect --staged --config .gitleaks.toml' > .husky/pre-commit
```

### 8.5 Environment matrix + drift audit (`docs/secret-env-matrix.json`, `.github/workflows/secret-env-audit.yml`)

`docs/secret-env-matrix.json` is the machine-readable source of truth for secret-name governance:

- Railway expectations are scoped by service (`api`, `worker`, `postgres`, `redis`).
- Vercel expectations are scoped by environment (`production`, `preview`, `development`).
- Rotation groups are defined once and reused by automation.

Audit workflow behavior (`Secret Env Audit`):

- Trigger: every Monday (`schedule`) and manually (`workflow_dispatch`).
- Reads provider env names only (never prints secret values).
- Computes `missing` + `extraneous` names against the matrix.
- Fails the run on strict scopes (`api`, `worker`, all Vercel envs).
- Keeps provider-managed services (`postgres`, `redis`) in advisory mode to avoid false blocking.

Required Actions secrets for audit:

- Railway: `RAILWAY_TOKEN`, `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_ID`, `RAILWAY_SERVICE_API_ID`, `RAILWAY_SERVICE_WORKER_ID` (optional advisory: `RAILWAY_SERVICE_POSTGRES_ID`, `RAILWAY_SERVICE_REDIS_ID`).
- Vercel: `VERCEL_TOKEN`, `VERCEL_PROJECT_ID` (optional: `VERCEL_TEAM_ID`).

### 8.6 Distribution automation (`.github/workflows/secret-rotate.yml`)

Manual rotation workflow behavior (`Secret Rotate`):

- Trigger: `workflow_dispatch` only.
- Inputs:
  - `group`: one group from `docs/secret-env-matrix.json`.
  - `target`: `all`, `railway`, or `vercel`.
  - `dry_run`: preview mode (`true` by default).
  - `confirm`: must be `ROTATE` when `dry_run=false`.
- Supported automated groups:
  - `api_access_key`
  - `dashboard_jwt_secret`
  - `auth_session_secret`
  - `admin_retry_api_key`
- Blocked manual-only groups:
  - `fernet`
  - `github_oauth`
  - `app_private_key_pem`
  - `webhook_secret`

Safety and logging:

- Generated values are randomized in-run and never echoed.
- Provider updates are performed via API calls; logs include only provider/scope/key names.
- The workflow writes `rotation-log.updated.json` as an artifact (date + metadata only), so you can review and then manually copy/commit to `docs/rotation-log.json`.
- Workflow permissions remain least-privilege (`contents: read`).

Safe sequence for an automated rotation window:

1. Run `Secret Env Audit` and resolve drift first.
2. Run `Secret Rotate` with `dry_run=true` and verify the plan.
3. Re-run with `dry_run=false` and `confirm=ROTATE`.
4. Smoke test: webhook delivery health, dashboard login, API auth path, worker jobs.
5. Apply artifact changes to `docs/rotation-log.json`, commit, and run audit again.

Rollback guidance:

- If a rotated value causes incidents, immediately re-run `Secret Rotate` for the same group/target to issue a fresh value and deploy consistently.
- For split systems (Railway + Vercel), prefer `target=all` to avoid transient mismatch.
- For `AUTH_SESSION_SECRET` / `DASHBOARD_USER_JWT_SECRET`, user re-authentication is expected after rollback/redo.
- Manual-only groups keep provider-native rollback procedures from Sections 3-4.

Automation limitations:

- This workflow does not auto-commit repository files.
- `FERNET_KEY`, webhook secret, OAuth secret, and app private key rotation remain manual by design.
- Postgres/Redis provider-managed variables are audited in advisory mode only.

---

## 9. Related files

- Repo-root `.env.example` — backend and shared names.
- `apps/web/.env.example` — Vercel / Next server secrets.
- `docs/secret-env-matrix.json` — expected env names by Railway service and Vercel environment; rotation group routing.
- `docs/rotation-log.json` — machine-readable rotation dates (update after every rotation).
- `.gitleaks.toml` — gitleaks scan configuration and allowlists.
- `README.md` — deployment targets (Railway API + worker, Vercel web).
- `.github/workflows/secret-scan.yml` — gitleaks CI scan (every push/PR).
- `.github/workflows/secret-rotation-reminder.yml` — weekly staleness check.
- `.github/workflows/secret-env-audit.yml` — matrix drift audit for env variable names.
- `.github/workflows/secret-rotate.yml` — manual distribution automation for allowed secret groups.
- `.github/workflows/quality-gates.yml`, `api-db-security.yml`, `deepeval.yml` — Actions secret names.
