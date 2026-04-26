from app.config import _database_url_has_ssl


def test_database_url_has_ssl_accepts_railway_managed_host_without_query_params() -> None:
    assert _database_url_has_ssl("postgresql://u:p@roundhouse.proxy.rlwy.net:5432/railway")


def test_database_url_has_ssl_false_for_generic_host_without_tls_query() -> None:
    assert not _database_url_has_ssl("postgresql://u:p@db.example.com:5432/app")


def test_database_url_has_ssl_true_for_ssl_query() -> None:
    assert _database_url_has_ssl("postgresql://u:p@db.example.com:5432/app?ssl=require")
