import unicodedata


def normalize_file_content(content: str) -> str:
    """Canonicalize file text so every consumer sees identical line endings."""
    return content.replace("\r\n", "\n").replace("\r", "\n")


def normalize_for_match(content: str) -> str:
    """Normalize line text for robust matching in repair/telemetry paths."""
    return unicodedata.normalize("NFC", content).lstrip("\ufeff").replace("\t", "    ").rstrip()

