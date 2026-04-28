from __future__ import annotations

import re
from collections import Counter

from app.agent.external.github_public import fetch_file_sample
from app.agent.external.types import ExternalFileDescriptor, PrepassPlan, PrepassSignals
from app.config import settings
from app.llm.catalog.loader import load_baseline_catalog
from app.llm.types import ModelRecord

_PROMPT_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+previous\s+instructions",
        r"system\s+prompt",
        r"developer\s+message",
        r"you\s+must\s+obey",
        r"bypass\s+safety",
        r"disable\s+guardrail",
    )
]

_FILLER_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(lorem ipsum(?:\s+lorem ipsum)+)",
        r"(foo|bar|baz)[\s,;]+(foo|bar|baz)[\s,;]+(foo|bar|baz)",
        r"(test|dummy|sample)[-_ ]?(data|file|content){2,}",
    )
]

_RISKY_PATH_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(^|/)\.github/workflows/",
        r"(^|/)docker",
        r"(^|/)k8s/",
        r"(^|/)terraform/",
        r"(^|/)secrets?",
        r"(^|/)auth",
        r"(^|/)middleware",
        r"(^|/)payments?",
    )
]

_IGNORED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".lock", ".min.js", ".svg")
_IGNORED_DIR_PREFIXES = ("node_modules/", "vendor/", "dist/", "build/", ".next/", ".git/")


def _provider_is_configured(provider: str) -> bool:
    if provider == "gemini":
        return bool((settings.gemini_api_key or "").strip())
    if provider == "openai":
        return bool((settings.openai_api_key or "").strip())
    if provider == "anthropic":
        return bool((settings.anthropic_api_key or "").strip())
    return False


def _fast_pass_model() -> str:
    catalog = load_baseline_catalog()
    active_models: list[ModelRecord] = [
        record
        for record in catalog.models
        if record.status == "active" and record.tier == "economy" and _provider_is_configured(record.provider)
    ]
    if not active_models:
        return "heuristic-lite-v1"
    # Pick the cheapest active economy model among configured providers.
    # Some provider catalogs occasionally omit pricing fields for economy models.
    fallback_input_price_by_model = {
        "gemini-2.5-flash": 0.20,
    }
    fallback_output_price_by_model = {
        "gemini-2.5-flash": 0.80,
    }

    def sort_key(record: ModelRecord) -> tuple[float, float, int, str]:
        input_price = (
            float(record.pricing.input_per_1m)
            if record.pricing.input_per_1m is not None
            else fallback_input_price_by_model.get(record.model, 10_000.0)
        )
        output_price = (
            float(record.pricing.output_per_1m)
            if record.pricing.output_per_1m is not None
            else fallback_output_price_by_model.get(record.model, 10_000.0)
        )
        return (input_price, output_price, -record.score, record.model)

    fastest = sorted(active_models, key=sort_key)[0]
    return f"{fastest.provider}:{fastest.model}"


def _looks_like_filler(text: str) -> bool:
    compact = " ".join(text.split())
    if any(pattern.search(compact) for pattern in _FILLER_PATTERNS):
        return True
    if len(compact) < 80:
        return False
    if len(set(compact)) <= 6:
        return True
    if max(Counter(compact).values()) > len(compact) * 0.4:
        return True
    return False


def _is_ignored_path(path: str) -> bool:
    normalized = path.strip().lower()
    if normalized.endswith(_IGNORED_SUFFIXES):
        return True
    return normalized.startswith(_IGNORED_DIR_PREFIXES)


def _is_risky_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in _RISKY_PATH_PATTERNS)


def _recommended_plan(file_count: int, risky_paths: int) -> PrepassPlan:
    fast_pass_model = _fast_pass_model()
    if file_count >= 2500 or risky_paths >= 120:
        return PrepassPlan(
            service_tier="high",
            shard_count=20,
            shard_size_target=140,
            cheap_pass_model=fast_pass_model,
            notes=["Large repository footprint; prioritize high-risk areas first."],
        )
    if file_count >= 800 or risky_paths >= 40:
        return PrepassPlan(
            service_tier="balanced",
            shard_count=10,
            shard_size_target=120,
            cheap_pass_model=fast_pass_model,
            notes=["Medium repository footprint; use balanced shard concurrency."],
        )
    return PrepassPlan(
        service_tier="economy",
        shard_count=4,
        shard_size_target=100,
        cheap_pass_model=fast_pass_model,
        notes=["Smaller repository; fewer shards reduce coordination overhead."],
    )


async def run_prepass(
    *,
    repo_ref_owner: str,
    repo_ref_repo: str,
    repo_ref_ref: str,
    files: list[ExternalFileDescriptor],
    fetch_samples_limit: int = 80,
) -> tuple[PrepassSignals, PrepassPlan]:
    from app.agent.external.github_public import PublicRepoRef

    repo_ref = PublicRepoRef(
        owner=repo_ref_owner,
        repo=repo_ref_repo,
        ref=repo_ref_ref,
        default_branch=repo_ref_ref,
    )
    signals = PrepassSignals()
    inspectable: list[ExternalFileDescriptor] = []
    for descriptor in files:
        if _is_ignored_path(descriptor.path):
            signals.ignored_paths.append(descriptor.path)
            continue
        inspectable.append(descriptor)
        if _is_risky_path(descriptor.path):
            signals.risky_paths.append(descriptor.path)

    for descriptor in inspectable[:fetch_samples_limit]:
        sample = await fetch_file_sample(repo_ref, descriptor.path)
        if not sample:
            continue
        lower = sample.lower()
        if any(pattern.search(lower) for pattern in _PROMPT_INJECTION_PATTERNS):
            signals.prompt_injection_paths.append(descriptor.path)
        if _looks_like_filler(sample):
            signals.filler_paths.append(descriptor.path)

    plan = _recommended_plan(len(inspectable), len(signals.risky_paths))
    return signals, plan

