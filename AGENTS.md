# AGENTS.md

## Cursor Cloud specific instructions

### Architecture overview

This is a monorepo for **Nash AI**, a GitHub App that reviews pull requests using Claude/OpenAI/Gemini. It has:
- **Backend** (`apps/api/`): Python 3.12 + FastAPI + SQLAlchemy 2.0 + ARQ (Redis queue)
- **Frontend** (`apps/web/`): Next.js 16 + TypeScript + Zustand + TanStack Query
- **Shared types** (`packages/shared-types/`): TypeScript types shared across apps

### Services (local dev)

| Service | Port | Command |
|---------|------|---------|
| Postgres 16 (SSL) | 5433 | `sudo docker compose up -d postgres` |
| Redis 7 | 6379 | `sudo docker compose up -d redis` |
| FastAPI API | 8000 | `cd apps/api/src && uv run python -m uvicorn app.main:app --reload --port 8000` |
| ARQ Worker | — | `cd apps/api/src && uv run python -m arq app.queue.worker.WorkerSettings` |
| Next.js Web | 3000 | `cd apps/web && pnpm dev` |

### Starting infrastructure

```bash
# Start Docker daemon (needed in Cloud Agent VMs)
sudo dockerd &>/tmp/dockerd.log &
sleep 3

# Start Postgres + Redis
sudo docker compose up -d
```

### Running tests

- **Backend**: `cd apps/api && TEST_DATABASE_URL="postgresql+asyncpg://dev:dev@localhost:5433/codereview_test" DATABASE_URL="postgresql+asyncpg://dev:dev@localhost:5433/codereview_test" REDIS_URL=redis://localhost:6379 uv run pytest tests/ --ignore=tests/deep_eval -m "not live_github and not live_llm"`
- **Frontend**: `cd apps/web && pnpm test`

### Running lint/typecheck

- **Backend lint**: `uv run ruff check apps/api/src`
- **Backend format**: `uv run ruff format apps/api/src`
- **Frontend lint**: `pnpm lint:web`
- **Frontend typecheck**: `pnpm typecheck:web`

### Key gotchas

1. **Test DB URL must omit `?ssl=require`**: The test conftest uses raw `asyncpg.connect()` to create the test database, and asyncpg cannot use `ssl=require` as a query parameter when Postgres SSL is already negotiated. Use `postgresql+asyncpg://dev:dev@localhost:5433/codereview_test` (without `?ssl=require`) for `TEST_DATABASE_URL` and `DATABASE_URL` when running pytest. The main API/worker should still use `?ssl=require`.

2. **Docker needs manual daemon start**: In Cloud Agent VMs, Docker is installed but `dockerd` must be started manually with `sudo dockerd &>/tmp/dockerd.log &`. Wait ~3 seconds before running `docker compose`.

3. **TLS certs for Postgres**: Before first `docker compose up`, generate certs: `cd apps/api && uv run python scripts/generate_postgres_local_tls.py`. The docker-compose mounts `apps/api/certs/postgres/` into the Postgres container.

4. **`.env` file location**: The API config resolver looks for `.env` files at `apps/api/.env`, `apps/api/.env.local`, repo root `.env`, and repo root `.env.local` (in that priority order, later overrides earlier). For local dev, copy `.env.example` to `apps/api/.env` and fill in a `FERNET_KEY`.

5. **`ENABLE_REVIEWS=false`** for local dev without LLM keys: Set this in `.env` to prevent the worker from attempting real LLM calls.

6. **pnpm blocked build scripts**: pnpm may warn about blocked build scripts for `esbuild`, `sharp`, and `unrs-resolver`. These packages ship pre-built binaries so the warning is safe to ignore for development.

7. **Alembic migrations**: Run from `apps/api/` with `DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview?ssl=require uv run python -m alembic upgrade head`. Same for the test DB (swap `codereview` for `codereview_test`, omit `?ssl=require`).
