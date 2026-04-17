-- Run: psql $DATABASE_URL -f migrations.sql
-- Or use Alembic (recommended for production): alembic upgrade head

CREATE TABLE IF NOT EXISTS users (
    id          BIGSERIAL PRIMARY KEY,
    github_id   BIGINT UNIQUE NOT NULL,
    login       TEXT NOT NULL,
    token_enc   BYTEA,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS installations (
    id              BIGSERIAL PRIMARY KEY,
    installation_id BIGINT UNIQUE NOT NULL,
    account_login   TEXT NOT NULL,
    account_type    TEXT NOT NULL,
    installed_at    TIMESTAMPTZ DEFAULT now(),
    suspended_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS repo_configs (
    id              BIGSERIAL PRIMARY KEY,
    installation_id BIGINT REFERENCES installations(installation_id),
    repo_full_name  TEXT NOT NULL,
    config_yaml     JSONB,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(installation_id, repo_full_name)
);

CREATE TABLE IF NOT EXISTS reviews (
    id              BIGSERIAL PRIMARY KEY,
    installation_id BIGINT REFERENCES installations(installation_id),
    repo_full_name  TEXT NOT NULL,
    pr_number       INT NOT NULL,
    pr_head_sha     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    model           TEXT NOT NULL,
    findings        JSONB,
    tokens_used     INT,
    cost_usd        NUMERIC(10, 6),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reviews_repo_pr ON reviews(repo_full_name, pr_number);
