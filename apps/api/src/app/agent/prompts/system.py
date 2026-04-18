from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=64)
def _load_file(relative_path: str) -> str:
    return (PROMPTS_DIR / relative_path).read_text(encoding="utf-8").strip()


def build_system_prompt(frameworks: list[str], repo_additions: str | None = None) -> str:
    parts = [
        _load_file("core_rules.md"),
        _load_file("fewshot_examples.md"),
    ]

    for framework in sorted(frameworks):
        stack_path = PROMPTS_DIR / "stacks" / f"{framework}.md"
        if stack_path.exists():
            stack_rules = _load_file(f"stacks/{framework}.md")
            parts.append(f"## Stack-specific rules: {framework}\n\n{stack_rules}")

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
