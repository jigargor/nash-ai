import re

TRAILING_EMPTY_BULLET = re.compile(r"^\s*[-*+]\s*$")


def sanitize_markdown_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").rstrip()
    if not normalized:
        return normalized

    lines = normalized.split("\n")
    while lines and TRAILING_EMPTY_BULLET.match(lines[-1]):
        lines.pop()
    return "\n".join(lines).rstrip()


def truncate_markdown_text(text: str, max_length: int) -> str:
    if max_length <= 0:
        return ""
    cleaned = sanitize_markdown_text(text)
    if len(cleaned) <= max_length:
        return cleaned

    candidate = cleaned[:max_length].rstrip()
    candidate = _truncate_at_safe_boundary(candidate)
    candidate = sanitize_markdown_text(candidate)
    return candidate


def _truncate_at_safe_boundary(text: str) -> str:
    double_newline = text.rfind("\n\n")
    if double_newline >= 0 and double_newline >= len(text) - 240:
        return text[:double_newline].rstrip()

    newline = text.rfind("\n")
    if newline >= 0 and newline >= len(text) - 240:
        return text[:newline].rstrip()

    last_space = text.rfind(" ")
    if last_space >= 0 and last_space >= len(text) - 80:
        return text[:last_space].rstrip()

    return text.rstrip()
