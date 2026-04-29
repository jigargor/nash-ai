#!/usr/bin/env python3
import json
import re
import sys
from typing import Any


SENSITIVE_PATTERNS = (
    r"^apps/api/src/app/webhooks/",
    r"^apps/api/src/app/api/",
    r"^apps/api/src/app/db/",
    r"^apps/api/alembic/",
    r"^apps/web/src/app/api/",
    r"^apps/web/src/middleware\.ts$",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_pr_context(payload: dict[str, Any]) -> bool:
    text = json.dumps(payload).lower()
    return "pull_request" in text or "pr_" in text


def _read_changed_files(payload: dict[str, Any]) -> list[str]:
    arguments = _as_dict(payload.get("arguments")) or _as_dict(payload.get("input"))
    files = arguments.get("changed_files")
    if not isinstance(files, list):
        return []
    return [item for item in files if isinstance(item, str)]


def _risk_result(files: list[str]) -> dict[str, Any]:
    sensitive: list[str] = []
    for file_path in files:
        if any(re.search(pattern, file_path) for pattern in SENSITIVE_PATTERNS):
            sensitive.append(file_path)

    has_migration = any(file_path.startswith("apps/api/alembic/") for file_path in files)
    score = min(100, len(sensitive) * 20 + (20 if has_migration else 0))

    return {
        "risk_score": score,
        "sensitive_touches": sensitive,
        "requires_path_aware_strictness": len(sensitive) > 0,
        "requires_migration_safety_review": has_migration,
    }


def main() -> int:
    raw = sys.stdin.read()
    payload = _as_dict(json.loads(raw)) if raw.strip() else {}

    if not _is_pr_context(payload):
        print(json.dumps({"additional_context": "Risk scoring skipped: not a PR context event."}))
        return 0

    files = _read_changed_files(payload)
    result = _risk_result(files)
    print(json.dumps({"additional_context": json.dumps(result)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
