from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def is_railway_managed_postgres_host(hostname: str | None) -> bool:
    """True when DATABASE_URL points at Railway's managed Postgres endpoints.

    Railway often omits ``sslmode`` / ``ssl`` in the URL while still requiring TLS
    for public proxy hostnames (e.g. ``*.rlwy.net``). Private mesh hostnames are
    treated as platform-controlled transport for production checks.
    """
    if not hostname:
        return False
    host = hostname.lower()
    return (
        host.endswith(".railway.app")
        or host.endswith(".rlwy.net")
        or host.endswith(".railway.internal")
    )


def normalize_asyncpg_database_url(database_url: str) -> str:
    """Return a URL SQLAlchemy can use with asyncpg.

    Hosted Postgres (Railway, Heroku, Render, etc.) often sets ``DATABASE_URL`` to
    ``postgres://`` or ``postgresql://`` without a driver. That makes
    ``create_async_engine`` fall back to the synchronous psycopg2 dialect, which
    we do not ship — normalize to ``postgresql+asyncpg``.
    """
    parsed = urlparse(database_url)
    scheme = parsed.scheme
    if scheme == "postgres":
        parsed = parsed._replace(scheme="postgresql+asyncpg")
    elif scheme == "postgresql":
        parsed = parsed._replace(scheme="postgresql+asyncpg")

    if not parsed.query:
        if is_railway_managed_postgres_host(parsed.hostname):
            return urlunparse(parsed._replace(query="ssl=require"))
        return urlunparse(parsed)

    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    has_ssl = any(key == "ssl" for key, _ in pairs)
    has_sslmode = any(key == "sslmode" for key, _ in pairs)
    if is_railway_managed_postgres_host(parsed.hostname) and not has_ssl and not has_sslmode:
        pairs.append(("ssl", "require"))

    normalized_pairs: list[tuple[str, str]] = []
    sslmode_value: str | None = None
    for key, value in pairs:
        if key == "sslmode":
            if sslmode_value is None:
                sslmode_value = value
            continue
        normalized_pairs.append((key, value))

    if sslmode_value and not has_ssl:
        normalized_pairs.append(("ssl", sslmode_value))

    normalized_query = urlencode(normalized_pairs, doseq=True)
    return urlunparse(parsed._replace(query=normalized_query))
