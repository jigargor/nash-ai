"""Mutation-seeded golden generator — inject a known defect into a clean file.

Each mutation ships its own clean base file so cases are self-consistent: the
``diff.patch`` is a real unified diff, ``context.json`` holds the mutated file at
HEAD, and ``expected.json`` points at the exact mutated line.

    python evals/harness/mutations.py --generate            # writes evals/datasets/mutation_*
    python evals/harness/mutations.py --generate --force    # overwrite existing cases
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = REPO_ROOT / "evals" / "datasets"

_WEBHOOK_PY = '''import hmac
import hashlib


def verify_signature(secret: bytes, body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_event(headers: dict[str, str]) -> str:
    return headers.get("X-GitHub-Event", "")
'''

_QUERY_PY = '''from typing import Any


def fetch_user(cursor: Any, user_id: str) -> dict[str, Any] | None:
    cursor.execute("SELECT id, login FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    return {"id": row[0], "login": row[1]}


def count_users(cursor: Any) -> int:
    cursor.execute("SELECT COUNT(*) FROM users")
    return int(cursor.fetchone()[0])
'''

_FETCH_PY = '''import requests


def fetch_status(url: str, timeout: float = 5.0) -> int:
    response = requests.get(url, timeout=timeout)
    return response.status_code


def fetch_json(url: str) -> dict:
    response = requests.get(url, timeout=5.0)
    response.raise_for_status()
    return response.json()
'''

_RUNNER_PY = '''import subprocess


def run_formatter(path: str) -> int:
    completed = subprocess.run(["ruff", "format", path], check=False)
    return completed.returncode


def run_tests(path: str) -> int:
    completed = subprocess.run(["pytest", path], check=False)
    return completed.returncode
'''

_CARD_TSX = '''import type { ReactNode } from "react";

interface CardProps {
  title: string;
  body: string;
  children?: ReactNode;
}

export function Card({ title, body, children }: CardProps) {
  return (
    <section className="card">
      <h3>{title}</h3>
      <p>{body}</p>
      {children}
    </section>
  );
}
'''

_CONFIG_PY = '''import os


def load_settings() -> dict[str, str]:
    api_key = os.environ.get("PAYMENTS_API_KEY", "")
    return {"api_key": api_key, "region": os.environ.get("REGION", "us-east-1")}
'''

MUTATIONS: list[dict[str, Any]] = [
    {
        "id": "py_hmac_eq",
        "file_path": "app/webhooks/verify.py",
        "base": _WEBHOOK_PY,
        "needle": "    return hmac.compare_digest(expected, signature)",
        "replacement": "    return expected == signature",
        "expected": {
            "severity": "high",
            "category": "security",
            "message": "Webhook signature compared with == instead of hmac.compare_digest.",
        },
        "title": "refactor(webhooks): simplify signature check",
        "body": "Small cleanup of the signature helper.",
    },
    {
        "id": "py_sql_fstring",
        "file_path": "app/db/users.py",
        "base": _QUERY_PY,
        "needle": '    cursor.execute("SELECT id, login FROM users WHERE id = %s", (user_id,))',
        "replacement": '    cursor.execute(f"SELECT id, login FROM users WHERE id = {user_id}")',
        "expected": {
            "severity": "critical",
            "category": "security",
            "message": "SQL constructed with f-string interpolates untrusted input.",
        },
        "title": "perf(db): inline user lookup query",
        "body": "Avoids the parameter tuple allocation on the hot path.",
    },
    {
        "id": "py_verify_false",
        "file_path": "app/http/fetch.py",
        "base": _FETCH_PY,
        "needle": "    response = requests.get(url, timeout=timeout)",
        "replacement": "    response = requests.get(url, timeout=timeout, verify=False)",
        "expected": {
            "severity": "high",
            "category": "security",
            "message": "TLS certificate verification disabled with verify=False.",
        },
        "title": "fix(http): work around staging cert errors",
        "body": "Staging uses self-signed certs; skip verification for status checks.",
    },
    {
        "id": "py_shell_true",
        "file_path": "app/tools/runner.py",
        "base": _RUNNER_PY,
        "needle": '    completed = subprocess.run(["ruff", "format", path], check=False)',
        "replacement": '    completed = subprocess.run("ruff format " + path, shell=True, check=False)',
        "expected": {
            "severity": "high",
            "category": "security",
            "message": "subprocess.run with shell=True and interpolated path enables command injection.",
        },
        "title": "chore(tools): use shell for formatter invocation",
        "body": "Lets us pass through shell globs.",
    },
    {
        "id": "tsx_dangerous_html",
        "file_path": "web/src/components/card.tsx",
        "base": _CARD_TSX,
        "needle": "      <p>{body}</p>",
        "replacement": "      <p dangerouslySetInnerHTML={{ __html: body }} />",
        "expected": {
            "severity": "high",
            "category": "security",
            "message": "dangerouslySetInnerHTML renders unsanitized body content (XSS).",
        },
        "title": "feat(card): support rich text bodies",
        "body": "Product wants bold/italic in card bodies.",
    },
    {
        "id": "py_hardcoded_secret",
        "file_path": "app/config/settings.py",
        "base": _CONFIG_PY,
        "needle": '    api_key = os.environ.get("PAYMENTS_API_KEY", "")',
        "replacement": '    api_key = os.environ.get("PAYMENTS_API_KEY", "sk_live_51HkQZ2eZvKYlo2C9x8mJ7q")',
        "expected": {
            "severity": "critical",
            "category": "security",
            "message": "Hard-coded live API key committed as a default value.",
        },
        "title": "fix(config): default payments key for local dev",
        "body": "Saves everyone from setting the env var locally.",
    },
]

# Clean control: a benign change that must produce zero findings.
CLEAN_CASES: list[dict[str, Any]] = [
    {
        "id": "clean_rename_helper",
        "file_path": "app/webhooks/verify.py",
        "base": _WEBHOOK_PY,
        "needle": 'def parse_event(headers: dict[str, str]) -> str:\n    return headers.get("X-GitHub-Event", "")',
        "replacement": (
            'def parse_event(headers: dict[str, str]) -> str:\n'
            '    """Return the GitHub event name (empty when missing)."""\n'
            '    return headers.get("X-GitHub-Event", "")'
        ),
        "title": "docs(webhooks): document parse_event",
        "body": "Docstring only.",
    }
]


def apply_mutation(source: str, mutation: dict[str, Any]) -> str | None:
    needle = str(mutation["needle"])
    if needle not in source:
        return None
    return source.replace(needle, str(mutation["replacement"]), 1)


def unified_diff(path: str, original: str, mutated: str) -> str:
    lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            mutated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )
    header = f"diff --git a/{path} b/{path}\n"
    return header + "".join(lines)


def first_changed_line(original: str, mutated: str) -> int:
    original_lines = original.split("\n")
    mutated_lines = mutated.split("\n")
    for idx, (a, b) in enumerate(zip(original_lines, mutated_lines), start=1):
        if a != b:
            return idx
    return min(len(original_lines), len(mutated_lines)) + 1


def write_case(*, dest_dir: Path, case: dict[str, Any], expect_finding: bool) -> Path:
    original = str(case["base"])
    mutated = apply_mutation(original, case)
    if mutated is None:
        raise RuntimeError(f"needle not found for mutation {case['id']}")
    file_path = str(case["file_path"])
    dest_dir.mkdir(parents=True, exist_ok=True)
    line_start = first_changed_line(original, mutated)
    expected: dict[str, Any] = {"findings": []}
    if expect_finding:
        expected["findings"].append(
            {**case["expected"], "file_path": file_path, "line_start": line_start}
        )
    (dest_dir / "context.json").write_text(
        json.dumps(
            {
                "repo": "nash-evals/mutations",
                "pr_number": 1,
                "head_sha": "0" * 40,
                "title": case.get("title", case["id"]),
                "body": case.get("body", ""),
                "files": {file_path: mutated},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (dest_dir / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    (dest_dir / "diff.patch").write_text(unified_diff(file_path, original, mutated), encoding="utf-8")
    return dest_dir


def generate_all(*, datasets_dir: Path = DATASETS_DIR, force: bool = False) -> list[Path]:
    written: list[Path] = []
    for case in MUTATIONS:
        dest = datasets_dir / f"mutation_{case['id']}"
        if dest.exists() and not force:
            continue
        written.append(write_case(dest_dir=dest, case=case, expect_finding=True))
    for case in CLEAN_CASES:
        dest = datasets_dir / f"mutation_{case['id']}"
        if dest.exists() and not force:
            continue
        written.append(write_case(dest_dir=dest, case=case, expect_finding=False))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate mutation-seeded golden cases")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--datasets-dir", default=str(DATASETS_DIR))
    args = parser.parse_args(argv)
    if not args.generate:
        parser.print_help()
        return 0
    written = generate_all(datasets_dir=Path(args.datasets_dir), force=args.force)
    for path in written:
        print(f"wrote {path}")
    print(f"{len(written)} case(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
