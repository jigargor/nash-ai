from app.db.url import is_railway_managed_postgres_host, normalize_asyncpg_database_url


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


def test_is_railway_managed_postgres_host() -> None:
    assert is_railway_managed_postgres_host("roundhouse.proxy.rlwy.net")
    assert is_railway_managed_postgres_host("postgres.railway.internal")
    assert not is_railway_managed_postgres_host("db.example.com")
    assert not is_railway_managed_postgres_host(None)


def test_normalize_asyncpg_database_url_adds_ssl_for_railway_proxy_without_query() -> None:
    raw_url = "postgresql://postgres:secret@roundhouse.proxy.rlwy.net:12345/railway"
    normalized = normalize_asyncpg_database_url(raw_url)
    assert normalized.startswith("postgresql+asyncpg://")
    assert "ssl=require" in normalized


def test_normalize_asyncpg_database_url_adds_ssl_for_railway_when_query_has_no_ssl() -> None:
    raw_url = "postgresql://u:p@containers-us-west-99.railway.app:5432/railway?connect_timeout=10"
    normalized = normalize_asyncpg_database_url(raw_url)
    assert "ssl=require" in normalized
    assert "connect_timeout=10" in normalized
