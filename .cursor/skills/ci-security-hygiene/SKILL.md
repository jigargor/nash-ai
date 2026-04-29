---
name: ci-security-hygiene
description: "Maintain CI security/quality gates when changing workflows, dependency tooling, lint/type/test steps, audit policies, or merge-blocking checks for backend/frontend pipelines."
---

# ci-security-hygiene

## When to use

- Edit GitHub Actions workflows, required checks, or quality gate policy.
- Add/update Python or Node dependencies affecting audit/lint/type/test checks.
- Investigate CI regressions involving security scanners, migrations, or build/test gates.
- Introduce new automation that can alter merge safety standards.

## When not to use

- Local-only developer convenience scripts that do not affect CI policy.
- Pure feature implementation with no workflow/check impact.
- Changes isolated to docs or assets with no gating relevance.

## Preconditions

- Identify required checks for backend and frontend paths.
- Confirm secrets handling in CI uses GitHub Actions secrets only.
- Ensure workflow changes still validate migrations and production-like builds/tests.
- Verify dependency audits remain enforced at fail-on-high-risk thresholds.

## Step-by-step workflow

1. **Preserve baseline gates**
   - Keep lint, typecheck, tests, and migration verification in CI.
   - Ensure backend and frontend jobs trigger on relevant path changes.
2. **Keep security scans blocking**
   - Maintain Python (`bandit`, `pip-audit`) and Node (`pnpm audit`) checks.
   - Do not downgrade audit severity or silently ignore failures without policy signoff.
3. **Guard against broken merges**
   - Add conflict-marker checks when touching merge-heavy templates/configs.
   - Keep lockfile/dependency updates deterministic enough for reproducible CI outcomes.
4. **Validate infra assumptions**
   - Ensure DB service, env vars, and migration steps match runtime expectations.
   - Keep private key handling ephemeral in CI jobs.
5. **Control workflow blast radius**
   - Scope workflow triggers to impacted areas while preserving security coverage.
   - Avoid removing checks to speed up CI without equivalent replacement.
6. **Confirm green path and fail path**
   - Validate expected pass behavior on clean branch and fail behavior on known violations.

## Anti-patterns

- Removing security scans or making them non-blocking to reduce CI duration.
- Committing real secrets or static keys to satisfy workflow setup.
- Skipping migration checks while altering DB models/migrations.
- Broadening workflow permissions beyond read needs without explicit justification.
- Allowing unresolved conflict markers in committed YAML/config files.

## Concrete file anchors

- `.github/workflows/quality-gates.yml`
- `.github/workflows/api-db-security.yml`
- `.pre-commit-config.yaml`
- `apps/api/pyproject.toml`
- `apps/api/scripts/check_coverage.py`
- `apps/api/alembic/env.py`
- `apps/api/tests/`
- `apps/web/src/lib/api/client.test.ts`
- `pnpm-lock.yaml`
- `uv.lock`

## Minimal verification checklist

- [ ] Backend CI path runs lint, mypy, migrations, tests, and security audits.
- [ ] Frontend CI path runs lint, typecheck, tests, and dependency audit.
- [ ] Workflow changes do not require committed secrets/private keys.
- [ ] Conflict markers are absent from committed source/config files.
- [ ] Updated workflows pass on a representative branch/PR run.
