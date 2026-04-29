#!/usr/bin/env python3
import json
import sys
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _looks_like_pr_open_sync(payload: dict[str, Any]) -> bool:
    text = json.dumps(payload).lower()
    return any(token in text for token in ("pull_request", "opened", "synchronize", "synchronized"))


def _extract_context(payload: dict[str, Any]) -> dict[str, Any]:
    arguments = _as_dict(payload.get("arguments"))
    input_payload = _as_dict(payload.get("input"))
    source = arguments or input_payload

    owner = source.get("owner") or source.get("repo_owner")
    repo = source.get("repo") or source.get("repository")
    number = source.get("pull_number") or source.get("pr_number") or source.get("number")
    check_status = source.get("check_status") or source.get("status")
    changed_files = source.get("changed_files")
    commits = source.get("commits")
    owners_hint = source.get("owners") or source.get("codeowners")

    return {
        "context_pack": {
            "repo": f"{owner}/{repo}" if owner and repo else None,
            "pr_number": number,
            "checks": check_status,
            "changed_files": changed_files if isinstance(changed_files, list) else [],
            "commits": commits if isinstance(commits, list) else [],
            "owners": owners_hint if isinstance(owners_hint, list) else [],
            "required_sections": [
                "risk_hotspots",
                "failing_checks",
                "security_sensitive_paths",
                "review_summary",
            ],
        }
    }


def main() -> int:
    raw = sys.stdin.read()
    payload = _as_dict(json.loads(raw)) if raw.strip() else {}

    if not _looks_like_pr_open_sync(payload):
        print(json.dumps({"additional_context": "No PR open/sync signal detected. Context-pack hook skipped."}))
        return 0

    context_pack = _extract_context(payload)
    print(json.dumps({"additional_context": json.dumps(context_pack)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
