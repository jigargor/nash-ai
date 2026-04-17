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
DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview python -m alembic upgrade head
DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview python -m alembic current
```

### 5. Verify GitHub App auth flow

```bash
cd apps/api
python -m pytest tests/test_github_auth.py

# Integration smoke-check (uses GITHUB_INSTALLATION_ID if provided;
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

# Terminal 2 — Web
cd apps/web && pnpm dev
```

### 8. Webhook smoke test checklist

1. Confirm the GitHub App is installed on at least one repository.
2. Open or update a test pull request on an installed repository.
3. Confirm smee logs a forwarded POST to `/webhooks/github`.
4. Confirm API logs include:
   - `GitHub webhook received event=pull_request ... payload_preview=...`
   - `PR webhook parsed installation_id=... repo=... pr_number=... head_sha=...`

If no installation exists yet, install the app first from its GitHub App page, then retry.

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
