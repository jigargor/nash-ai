#!/usr/bin/env python3
import json
import re
import sys
from typing import Any


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


def _score(files: list[str]) -> dict[str, Any]:
    source_files = [f for f in files if re.search(r"\.(py|ts|tsx|js|jsx|rs)$", f)]
    test_files = [f for f in files if re.search(r"(^|/)(test|tests|__tests__)/|(\.test\.|\.spec\.)", f)]

    needs_test_warning = len(source_files) > 0 and len(test_files) == 0
    score = 90 if needs_test_warning else 20
    return {
        "test_gap_score": score,
        "source_files": len(source_files),
        "test_files": len(test_files),
        "needs_test_warning": needs_test_warning,
    }


def main() -> int:
    raw = sys.stdin.read()
    payload = _as_dict(json.loads(raw)) if raw.strip() else {}

    if not _is_pr_context(payload):
        print(json.dumps({"additional_context": "Test-gap scoring skipped: not a PR context event."}))
        return 0

    files = _read_changed_files(payload)
    result = _score(files)
    print(json.dumps({"additional_context": json.dumps(result)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
