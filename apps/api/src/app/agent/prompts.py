SYSTEM_PROMPT = """
You are an expert code reviewer. Focus on correctness, security, and performance.
Prefer actionable comments tied to concrete lines in changed files.
Use tools when needed to gather missing context.
Avoid speculative findings; include confidence scores.
""".strip()


def build_initial_user_prompt(owner: str, repo: str, pr_number: int, diff_text: str, context_bundle: str) -> str:
    return f"""
Review pull request #{pr_number} in {owner}/{repo}.

Unified diff:
{diff_text}

Additional code context:
{context_bundle}

Find important issues only. Use tools if additional evidence is needed.
""".strip()
