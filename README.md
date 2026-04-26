# AI Code Review Agent

Automated pull request reviews powered by multi-model LLM orchestration and the GitHub App API.

## What it does

- **Inline reviews** on pull requests using the GitHub Review Comments API (severity-ranked findings, optional `suggestion` blocks).
- **Tool-augmented agent** (fetch files, search repo, etc.) with layered diff context, validation, and an editor pass before posting.
- **Per-repository config** via `.codereview.yml` (model, budgets, confidence/severity filters, category allowlists, ignore globs, draft PR handling, finding caps)—cached in **Redis** by branch SHA.
- **Operational guardrails**: per-installation review rate limits, daily token budget accounting, and an **`ENABLE_REVIEWS`** kill switch for incidents.
- **Optional observability**: Sentry for errors, Langfuse-compatible Anthropic client wiring and review trace metadata.
- **Quality gates**: Ruff, Mypy, pytest with agent coverage floor, Bandit, and an optional **prompt-change** PR workflow that runs a small golden eval harness under `evals/`.

## Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + ARQ (Redis queue)
- **Frontend**: Next.js 15 + TypeScript + Zustand + TanStack Query
- **AI**: Anthropic + OpenAI + Gemini (provider/model selectable per repository via `.codereview.yml`)
- **Infra**: Postgres + Redis (docker-compose locally, Railway in prod)

## Observability (optional)

Set these in `apps/api` (or repo-root) environment when you want telemetry; the API and worker both call `init_observability` on startup.

| Variable | Purpose |
|----------|---------|
| `SENTRY_DSN` | Error reporting (FastAPI + worker). |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse project keys when tracing model calls. |
| `LANGFUSE_HOST` | Langfuse API host (e.g. `https://cloud.langfuse.com`). |

## Evaluations

Golden-style cases live under `evals/datasets/` (expected findings + optional diff/context fixtures). Run:

```bash
python evals/run_eval.py --prompt-version <label> --predictions-dir evals/predictions/<label>
python evals/compare.py evals/results/baseline.json evals/results/<label>.json
```

CI runs the harness on pull requests labeled **`prompt-change`** (see `.github/workflows/quality-gates.yml`).

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
# Fill in GITHUB_APP_ID, GITHUB_WEBHOOK_SECRET, and at least one LLM provider API key.
# Prefer APP_PRIVATE_KEY_PEM on hosted environments; keep APP_PRIVATE_KEY_PEM_PATH for local dev.
# Windows note: use forward slashes for APP_PRIVATE_KEY_PEM_PATH
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
DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview?ssl=require python -m alembic upgrade head
DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview?ssl=require python -m alembic current
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

### 10. Repository review configuration (`.codereview.yml`)

Each repo can add a `.codereview.yml` at the default branch ref used for the review. The worker loads it for confidence threshold, optional prompt additions, **model name and pricing** (for `cost_usd` estimates), **token budgets**, and **context packaging** flags.

Typical keys:

| Key | Purpose |
|-----|---------|
| `confidence_threshold` | Minimum finding confidence (0–1); default `0.85`. |
| `severity_threshold` | Minimum severity that can be posted (`low`/`medium`/`high`/`critical`). |
| `categories` | Optional allowlist of finding categories to keep (`security`, `performance`, `correctness`, `style`, `maintainability`). |
| `ignore_paths` | Glob patterns that are ignored for context packing and finding posting. |
| `review_drafts` | If `true`, review draft pull requests; default `false`. |
| `max_findings_per_pr` | Hard cap on posted findings after filtering. |
| `prompt_additions` | Extra repo-specific instructions appended to the system prompt. |
| `model.provider` | Model provider (`anthropic`, `openai`, `gemini`). |
| `model.name` | Provider-specific model id (e.g. `claude-sonnet-4-5`, `gpt-5.5`, `gemini-2.5-pro`). |
| `model.pricing` | Optional `input_per_1m` / `output_per_1m` (USD per 1M tokens) for cost estimation when defaults don’t match your billing. |
| `max_mode.enabled` | Enables primary+challenger review mode. |
| `max_mode.challenger` | Challenger provider/model used to validate primary findings. |
| `max_mode.tie_break` | Tie-break provider/model used only on conflicts/high-risk findings. |
| `max_mode.conflict_threshold` | Conflict score threshold (0-100) that triggers tie-break. |
| `budgets` | Token budgets for layers, e.g. `system_prompt`, `repo_profile`, `diff_hunks`, `surrounding_context`, `total_cap`, etc. |
| `layered_context_enabled` | Use layered project/repo/review context packing (default on). |
| `partial_review_mode_enabled` | For large PRs, scope review to top-ranked files (default on). |
| `partial_review_changed_lines_threshold` | Approximate changed-line count before partial mode applies (default `600`). |
| `summarization_enabled` | Structured fallback summaries for evicted context segments (default off). |
| `max_summary_calls_per_review` | Cap on summarization steps per review. |
| `generated_paths` / `vendor_paths` | Glob-style path patterns to treat generated or vendored files differently when packing context. |

Review jobs build **layered context** (project → repo profile/additions → diff hunks and surrounding lines), rank hunks for relevance, enforce anchor coverage for inline comments, and record packer telemetry. `.codereview.yml` is cached per `(owner, repo, sha)` in Redis for one hour. `tokens_used` / `cost_usd` on each `reviews` row reflect the selected model’s pricing when configured. When `max_mode` is enabled, the pipeline records per-stage audit rows for primary/challenger/tie-break decisions.

### 11. Production deployment

Backend deployment target: Railway.

- `apps/api/railway.toml` is for the **API** only: `python -m app.serve_railway` (reads `PORT`; avoids 502s when `$PORT` is not expanded in the shell).
- The **ARQ worker** is a second Railway service with the same root directory `apps/api`, but it **must not** use that file or Nixpacks will start the web server. Set the worker’s **config as code** path to `apps/api/railway.worker.json` (or set **Start command** to `python -m arq app.queue.worker.WorkerSettings` and **Healthcheck** to disabled; the JSON file also sets `healthcheckPath` to `null` because the worker has no HTTP port).
- Set `APP_PRIVATE_KEY_PEM` in Railway variables for both API and worker services.
- Keep `APP_PRIVATE_KEY_PEM_PATH` for local development fallback only.

Frontend deployment target: Vercel.

- Project root: `apps/web`
- Required backend URL wiring should use your deployed API domain.
- Set `WEB_APP_URL` in API env to the exact frontend origin for strict CORS.
- Vercel typically does not need `APP_PRIVATE_KEY_PEM` (web uses OAuth client ID/secret), unless you add a server route there that signs GitHub App JWTs.

### 12. Production security checklist

- Webhook signatures verified with `hmac.compare_digest`.
- Installation tokens are short-lived and never persisted.
- OAuth tokens are stored encrypted via Fernet.
- At least one LLM provider key is required when `ENABLE_REVIEWS=true`.
- `ENABLE_REVIEWS` kill switch is available for incident mitigation.
- `REVIEWS_PER_HOUR_LIMIT` and `DAILY_TOKEN_BUDGET_PER_INSTALLATION` are enforced.
- Sentry and Langfuse env vars should be configured in production.
- Run `uv run bandit -r src` and CI quality gates before deploy.

### 16. Privacy and GDPR notes

- Review processing transmits repository diffs and selected file context to configured model providers.
- You must establish data processing agreements with each enabled provider for production use.
- Use strict tenant scoping (RLS + installation context) for all review and audit tables.
- Configure data retention/deletion workflows for review artifacts before public launch.
- See `SECURITY.md` for coordinated vulnerability reporting requirements.

### 13. Incident response and runbook

See [`INCIDENTS.md`](INCIDENTS.md) for incident playbooks and the postmortem template.

### 14. Inspect dropped findings safely (tenant-scoped SQL)

The agent stores development diagnostics in `reviews.debug_artifacts`, including:
- validator drops (`reason`, `detail`, `file_path`, line range, message excerpt)
- confidence-threshold drops (`confidence`, `threshold`)
- retry metadata (`retry_triggered`, `retry_reason`)
- **context telemetry** (`context_telemetry`: layer token usage, anchor coverage, summarization flags, dropped segments)
- **agent metrics** (`agent_metrics`: e.g. turn count, `fetch_file_content` calls)

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

`debug_artifacts.validator_dropped` (with structured `reason` codes such as `target_line_mismatch`, `line_not_in_diff`, `syntax_invalid_suggestion`) and `debug_artifacts.confidence_dropped` are the fastest way to understand why a finding was not posted.

Optional admin API endpoint (same admin key / tenant checks):

```bash
curl -s "http://localhost:8000/admin/reviews/<review_id>/debug?installation_id=<installation_id>" \
  -H "x-admin-api-key: <ADMIN_RETRY_API_KEY>"
```

This returns `debug_artifacts` plus review summary/status and kept finding count.

### 15. Local Postgres SSL setup notes

- `docker-compose.yml` expects certs at `apps/api/certs/postgres/server.crt` and `apps/api/certs/postgres/server.key`.
- Regenerate certs any time with:

```bash
cd apps/api
python scripts/generate_postgres_local_tls.py
```

- Keep API, worker, Alembic, and tests on the same SSL URL shape:
  - `DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview?ssl=require`
  - `TEST_DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/codereview_test?ssl=require`
- If you intentionally run without SSL, switch both URLs to the plaintext fallback form (without `ssl=require`).

## Project Structure

```
apps/
  api/src/app/
    config.py       Settings (pydantic-settings)
    main.py         FastAPI app + lifespan
    github/         App JWT auth + API client
    webhooks/       HMAC verification + event routing
    agent/          ReAct loop, context packing, prompts, review config
    db/             Models, session, migrations
    observability.py Optional Sentry + Langfuse bootstrap
    ratelimit.py    Redis sliding-window and token budget helpers
  web/src/
    app/            Next.js App Router pages
    lib/            API client utilities
evals/
  datasets/         Golden eval cases
  predictions/      Model output fixtures for eval runs
  run_eval.py       Precision / recall / FP-rate metrics
  compare.py        Compare two eval result JSON files
packages/
  shared-types/     TypeScript types shared across apps
```
