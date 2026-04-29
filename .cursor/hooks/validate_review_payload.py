#!/usr/bin/env python3
import json
import re
import sys
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_review_publish(payload: dict[str, Any]) -> bool:
    text = json.dumps(payload).lower()
    keywords = ("review", "comment", "pull", "publish", "create_review")
    return all(token in text for token in ("pull", "review")) or any(token in text for token in keywords)


def _collect_text(arguments: dict[str, Any]) -> str:
    candidates: list[str] = []
    for key in ("body", "summary", "comment", "review", "message"):
        value = arguments.get(key)
        if isinstance(value, str):
            candidates.append(value)
    return "\n".join(candidates).lower()


def _check_sections(text: str) -> list[str]:
    required_patterns = {
        "severity": r"\bseverity\b",
        "reproduction": r"\b(repro|reproduction|steps to reproduce|observed)\b",
        "suggested_fix": r"\b(suggestion|suggested fix|recommended fix|```suggestion)\b",
    }
    missing: list[str] = []
    for section, pattern in required_patterns.items():
        if re.search(pattern, text) is None:
            missing.append(section)
    return missing


def main() -> int:
    raw = sys.stdin.read()
    payload = _as_dict(json.loads(raw)) if raw.strip() else {}

    if not _is_review_publish(payload):
        print(json.dumps({"permission": "allow"}))
        return 0

    arguments = _as_dict(payload.get("arguments")) or _as_dict(payload.get("input"))
    review_text = _collect_text(arguments)
    missing = _check_sections(review_text)

    if missing:
        print(
            json.dumps(
                {
                    "permission": "deny",
                    "user_message": "Review publish blocked: include severity, reproduction signal, and suggested fix.",
                    "agent_message": f"Missing required review sections: {', '.join(missing)}",
                }
            )
        )
        return 0

    print(json.dumps({"permission": "allow"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
