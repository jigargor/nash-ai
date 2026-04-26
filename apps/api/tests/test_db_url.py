from app.db.url import normalize_asyncpg_database_url


def test_normalize_asyncpg_database_url_converts_sslmode_to_ssl() -> None:
    raw_url = "postgresql+asyncpg://dev:dev@localhost:5433/codereview?sslmode=require"
    normalized = normalize_asyncpg_database_url(raw_url)
    assert "ssl=require" in normalized
    assert "sslmode=" not in normalized


def test_normalize_asyncpg_database_url_keeps_explicit_ssl() -> None:
    raw_url = "postgresql+asyncpg://dev:dev@localhost:5433/codereview?ssl=true&sslmode=require"
    normalized = normalize_asyncpg_database_url(raw_url)
    assert "ssl=true" in normalized
    assert "sslmode=" not in normalized


def test_normalize_asyncpg_database_url_coerces_postgresql_scheme() -> None:
    raw_url = "postgresql://user:pass@host.example:5432/mydb"
    normalized = normalize_asyncpg_database_url(raw_url)
    assert normalized.startswith("postgresql+asyncpg://")


def test_normalize_asyncpg_database_url_coerces_postgres_scheme() -> None:
    raw_url = "postgres://user:pass@host.example:5432/mydb"
    normalized = normalize_asyncpg_database_url(raw_url)
    assert normalized.startswith("postgresql+asyncpg://")


def test_normalize_asyncpg_database_url_preserves_other_drivers() -> None:
    raw_url = "postgresql+psycopg://user:pass@localhost/db"
    assert normalize_asyncpg_database_url(raw_url) == raw_url
