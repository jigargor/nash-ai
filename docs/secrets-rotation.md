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

Mirror **both** services for shared config:

- **Core:** `DATABASE_URL`, `REDIS_URL`, `FERNET_KEY`, `ENVIRONMENT=production` (and TLS on `DATABASE_URL` per `config.py`).
- **GitHub:** `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `APP_PRIVATE_KEY_PEM` (preferred hosted form).
- **Auth / limits:** `API_ACCESS_KEY`, `ADMIN_RETRY_API_KEY`, `DASHBOARD_USER_JWT_SECRET` (must match web if the BFF signs JWTs with the same secret), `DASHBOARD_USER_JWT_AUDIENCE`, `DASHBOARD_USER_JWT_ISSUER`.
- **CORS / URLs:** `WEB_APP_URL` (exact frontend origin, no trailing slash).
- **LLM:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` (set whichever providers you enable).
- **Optional:** `SENTRY_DSN`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `R2_ENDPOINT_URL`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_REGION`, `R2_SNAPSHOT_PREFIX`, `ENABLE_REVIEWS`, rate/budget knobs.

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

## 7. Related files

- Repo-root `.env.example` — backend and shared names.
- `apps/web/.env.example` — Vercel / Next server secrets.
- `README.md` — deployment targets (Railway API + worker, Vercel web).
- `.github/workflows/quality-gates.yml`, `api-db-security.yml`, `deepeval.yml` — Actions secret names.
