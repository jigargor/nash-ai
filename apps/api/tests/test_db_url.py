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
