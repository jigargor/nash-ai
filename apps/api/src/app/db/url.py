from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def normalize_asyncpg_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    if not parsed.query:
        return database_url

    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    has_ssl = any(key == "ssl" for key, _ in pairs)

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
