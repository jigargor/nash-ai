from dataclasses import dataclass

import httpx
import yaml

DEFAULT_CONFIDENCE_THRESHOLD = 0.85


@dataclass
class ReviewConfig:
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    prompt_additions: str | None = None


async def load_review_config(gh, owner: str, repo: str, ref: str) -> ReviewConfig:
    try:
        raw_config = await gh.get_file_content(owner, repo, ".codereview.yml", ref)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return ReviewConfig()
        return ReviewConfig()
    except Exception:
        return ReviewConfig()

    try:
        parsed = yaml.safe_load(raw_config) or {}
    except yaml.YAMLError:
        return ReviewConfig()

    threshold = _normalize_threshold(parsed.get("confidence_threshold"))
    prompt_additions = parsed.get("prompt_additions")
    if prompt_additions is not None:
        prompt_additions = str(prompt_additions).strip() or None
    return ReviewConfig(confidence_threshold=threshold, prompt_additions=prompt_additions)


def _normalize_threshold(raw_value: object) -> float:
    if raw_value is None:
        return DEFAULT_CONFIDENCE_THRESHOLD
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE_THRESHOLD
    if value < 0.0 or value > 1.0:
        return DEFAULT_CONFIDENCE_THRESHOLD
    return value
