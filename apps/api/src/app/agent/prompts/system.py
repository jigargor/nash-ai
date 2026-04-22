from functools import lru_cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=64)
def _load_file(relative_path: str) -> str:
    return (PROMPTS_DIR / relative_path).read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _load_verified_facts() -> list[dict[str, object]]:
    facts_path = PROMPTS_DIR / "verified_facts.yaml"
    if not facts_path.exists():
        return []
    raw = yaml.safe_load(facts_path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized.append(item)
    return normalized


def load_verified_fact_ids() -> set[str]:
    fact_ids: set[str] = set()
    for fact in _load_verified_facts():
        fact_id = fact.get("id")
        if isinstance(fact_id, str) and fact_id.strip():
            fact_ids.add(fact_id.strip())
    return fact_ids


def build_system_prompt(frameworks: list[str], diff: str, repo_additions: str | None = None) -> str:
    parts = [
        _load_file("reviewer_system.md"),
        _load_file("fewshot_examples.md"),
    ]

    for framework in sorted(frameworks):
        stack_path = PROMPTS_DIR / "stacks" / f"{framework}.md"
        if stack_path.exists():
            stack_rules = _load_file(f"stacks/{framework}.md")
            parts.append(f"## Stack-specific rules: {framework}\n\n{stack_rules}")

    relevant_facts: list[str] = []
    diff_lower = diff.lower()
    for fact in _load_verified_facts():
        fact_id = str(fact.get("id", "")).strip()
        fact_text = str(fact.get("fact", "")).strip()
        keywords = fact.get("keywords", [])
        if not fact_id or not fact_text or not isinstance(keywords, list):
            continue
        if any(str(keyword).lower() in diff_lower for keyword in keywords):
            relevant_facts.append(f"**{fact_id}**: {fact_text}")
    if relevant_facts:
        parts.append("## Reminders from past reviews\n\n" + "\n\n".join(relevant_facts))

    if repo_additions:
        parts.append(f"## Additional context for this repository\n\n{repo_additions.strip()}")

    return "\n\n---\n\n".join(parts)


def build_initial_user_prompt(owner: str, repo: str, pr_number: int, diff_context: str) -> str:
    return f"""
Review pull request #{pr_number} in {owner}/{repo}.

Use the line-numbered context below to produce precise, evidence-backed findings.
If line content is missing or ambiguous, call tools (especially fetch_file_content) before finalizing.

{diff_context}
""".strip()
