# AI Code Review Agent

Automated pull request reviews powered by Claude and the GitHub App API.

## Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + ARQ (Redis queue)
- **Frontend**: Next.js 15 + TypeScript + Zustand + TanStack Query
- **AI**: Anthropic Claude (claude-sonnet-4-5)
- **Infra**: Postgres + Redis (docker-compose locally, Railway in prod)

## Quick Start

### 1. Install dependencies

```bash
# Python (from apps/api)
uv sync

# Node
pnpm install
```

### 2. Configure environment

```bash
cp .env.example apps/api/.env
# Fill in GITHUB_APP_ID, GITHUB_WEBHOOK_SECRET, ANTHROPIC_API_KEY, etc.
# Windows note: use forward slashes for GITHUB_PRIVATE_KEY_PATH
# e.g. C:/Users/you/Documents/2026/your-app.private-key.pem
```

### 3. Start infra

```bash
cd apps/api
python scripts/generate_postgres_local_tls.py
cd ../..
docker compose up -d
```

Health checks:

```bash
docker compose exec -T postgres pg_isready -U dev -d codereview
docker compose exec -T redis redis-cli ping
```

### 4. Run migrations

```bash
cd apps/api
# default compose postgres is exposed on localhost:5433
DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview?sslmode=require python -m alembic upgrade head
DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview?sslmode=require python -m alembic current
```

### 5. Verify GitHub App auth flow

```bash
cd apps/api
python -m pytest tests/test_github_auth.py

# Automated live GitHub integration test (requires app env + installation)
RUN_LIVE_GITHUB_TESTS=1 python -m pytest -m live_github tests/test_github_live_auth.py

# Optional smoke-check command (uses GITHUB_INSTALLATION_ID if provided;
# otherwise it discovers the first installation of the app)
python -m app.github.smoke_check
```

### 6. Start webhook tunnel

```bash
npx smee-client --url https://smee.io/YOUR_CHANNEL --target http://localhost:8000/webhooks/github
```

### 7. Start services

```bash
# Terminal 1 — API
cd apps/api/src && python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — Worker
cd apps/api/src && python -m arq app.queue.worker.WorkerSettings

# Terminal 3 — Web
cd apps/web && pnpm dev
```

### 8. Webhook smoke test checklist

1. Confirm the GitHub App is installed on at least one repository.
2. Open or update a test pull request on an installed repository.
3. Confirm smee logs a forwarded POST to `/webhooks/github`.
4. Confirm API logs include:
   - `GitHub webhook received event=pull_request ... payload_raw=...`
   - `Queued review job review_id=...`
   - `PR webhook parsed installation_id=... repo=... pr_number=... head_sha=...`

If no installation exists yet, install the app first from its GitHub App page, then retry.

### 9. Queue/worker validation checklist

1. Start API + worker (sections 6 and 7).
2. Trigger a `pull_request` webhook (`opened`/`synchronize`) with a valid signature.
3. Confirm API logs:
   - `Queued review job review_id=...`
4. Confirm review lifecycle in Postgres:

```bash
docker compose exec -T postgres psql -U dev -d codereview -c "select id, status, repo_full_name, pr_number, tokens_used, cost_usd from reviews order by id desc limit 5;"
```

Expected state transitions are `queued -> running -> done|failed`.

### 10. Inspect dropped findings safely (tenant-scoped SQL)

The agent now stores development diagnostics in `reviews.debug_artifacts`, including:
- validator drops (`reason`, `file_path`, line range, message excerpt)
- confidence-threshold drops (`confidence`, `threshold`)
- retry metadata (`retry_triggered`, `retry_reason`)

Because review tables use RLS, set the tenant context before querying.

1. Find your installation id:

```bash
docker compose exec -T postgres psql -U dev -d codereview -c "select installation_id, account_login from installations order by installed_at desc limit 20;"
```

2. Query reviews with tenant context:

```bash
docker compose exec -T postgres psql -U dev -d codereview -c "select set_config('app.current_installation_id','<installation_id>', true); select id, status, repo_full_name, pr_number, jsonb_array_length(coalesce(findings->'findings','[]'::jsonb)) as kept_findings, debug_artifacts from reviews order by id desc limit 10;"
```

3. Inspect one review in detail:

```bash
docker compose exec -T postgres psql -U dev -d codereview -c "select set_config('app.current_installation_id','<installation_id>', true); select id, findings, debug_artifacts from reviews where id=<review_id>;"
```

`debug_artifacts.validator_dropped` and `debug_artifacts.confidence_dropped` are the fastest way to understand why a finding was not posted.

### 11. Local Postgres SSL setup notes

- `docker-compose.yml` expects certs at `apps/api/certs/postgres/server.crt` and `apps/api/certs/postgres/server.key`.
- Regenerate certs any time with:

```bash
cd apps/api
python scripts/generate_postgres_local_tls.py
```

- Keep API, worker, Alembic, and tests on the same SSL URL shape:
  - `DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview?sslmode=require`
  - `TEST_DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview_test?sslmode=require`
- If you intentionally run without SSL, switch both URLs to the plaintext fallback form (without `sslmode=require`).

## Project Structure

```
apps/
  api/src/app/
    config.py       Settings (pydantic-settings)
    main.py         FastAPI app + lifespan
    github/         App JWT auth + API client
    webhooks/       HMAC verification + event routing
    agent/          ReAct loop (Phase 2)
    db/             Models, session, migrations
  web/src/
    app/            Next.js App Router pages
    lib/            API client utilities
packages/
  shared-types/     TypeScript types shared across apps
```
