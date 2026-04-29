import asyncio
import httpx

from app.agent.review_config import (
    _parse_adaptive_threshold,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_SEVERITY_THRESHOLD,
    _parse_budgets,
    _parse_categories,
    _parse_chunking,
    _parse_fast_path,
    _parse_max_mode,
    _parse_model_config,
    _parse_packaging,
    _parse_severity_threshold,
    load_review_config,
)


def test_parse_model_config_accepts_custom_pricing_override() -> None:
    model = _parse_model_config(
        {
            "provider": "anthropic",
            "name": "claude-3-5-haiku-latest",
            "pricing": {"input_per_1m": 1.5, "output_per_1m": 6.5},
        }
    )
    assert model.provider == "anthropic"
    assert model.name == "claude-3-5-haiku-latest"
    assert str(model.input_per_1m_usd) == "1.5"
    assert str(model.output_per_1m_usd) == "6.5"
    assert model.explicit is True


def test_parse_fast_path_reads_thresholds_and_flags() -> None:
    fast_path = _parse_fast_path(
        {
            "enabled": False,
            "skip_min_confidence": 95,
            "light_review_min_confidence": 82,
            "force_economy_on_light_review": True,
            "max_diff_excerpt_tokens": 1200,
            "allow_skip": False,
            "confidence_bug_check": False,
            "zero_confidence_limit": 7,
            "post_classification_context_comment": True,
        }
    )

    assert fast_path.enabled is False
    assert fast_path.skip_min_confidence == 95
    assert fast_path.light_review_min_confidence == 82
    assert fast_path.force_economy_on_light_review is True
    assert fast_path.max_diff_excerpt_tokens == 1200
    assert fast_path.allow_skip is False
    assert fast_path.confidence_bug_check is False
    assert fast_path.zero_confidence_limit == 7
    assert fast_path.post_classification_context_comment is True


def test_parse_adaptive_threshold_reads_guardrails() -> None:
    adaptive = _parse_adaptive_threshold(
        {
            "enabled": True,
            "initial_threshold": 90,
            "minimum_threshold": 70,
            "step_down": 3,
            "target_disagreement_low": 5,
            "target_disagreement_high": 12,
            "max_false_accept_rate": 4,
            "max_dismiss_rate": 20,
            "min_samples": 200,
        }
    )
    assert adaptive.enabled is True
    assert adaptive.initial_threshold == 90
    assert adaptive.minimum_threshold == 70
    assert adaptive.step_down == 3
    assert adaptive.target_disagreement_low == 5
    assert adaptive.target_disagreement_high == 12
    assert adaptive.max_false_accept_rate == 4
    assert adaptive.max_dismiss_rate == 20
    assert adaptive.min_samples == 200


def test_parse_model_config_accepts_legacy_direct_pricing_keys() -> None:
    model = _parse_model_config(
        {
            "provider": "anthropic",
            "name": "claude-sonnet-4-5",
            "input_per_1m_usd": 2.5,
            "cached_input_per_1m_usd": 0.25,
            "output_per_1m_usd": 8.5,
        }
    )

    assert str(model.input_per_1m_usd) == "2.5"
    assert str(model.cached_input_per_1m_usd) == "0.25"
    assert str(model.output_per_1m_usd) == "8.5"


def test_parse_budgets_overrides_known_values() -> None:
    budgets = _parse_budgets({"diff_hunks": 12345, "surrounding_context": 9000})
    assert budgets.diff_hunks == 12345
    assert budgets.surrounding_context == 9000


def test_parse_packaging_applies_threshold_paths_and_summary_cap() -> None:
    packaging = _parse_packaging(
        {
            "layered_context_enabled": True,
            "partial_review_mode_enabled": True,
            "summarization_enabled": False,
            "partial_review_changed_lines_threshold": 700,
            "max_summary_calls_per_review": 2,
            "generated_paths": ["src/generated/types.ts"],
            "vendor_paths": ["vendor/lib"],
        }
    )
    assert packaging.partial_review_changed_lines_threshold == 700
    assert packaging.max_summary_calls_per_review == 2
    assert packaging.generated_paths == ["src/generated/types.ts"]
    assert packaging.vendor_paths == ["vendor/lib"]


def test_parse_severity_threshold_defaults_on_unknown_value() -> None:
    assert _parse_severity_threshold("high") == "high"
    assert _parse_severity_threshold("unknown") == DEFAULT_SEVERITY_THRESHOLD


def test_parse_categories_filters_to_supported_values() -> None:
    assert _parse_categories(["security", "style", "bogus", 1]) == ["security", "style"]


def test_parse_chunking_reads_thresholds_and_included_classes() -> None:
    chunking = _parse_chunking(
        {
            "enabled": True,
            "proactive_threshold_tokens": 31000,
            "target_chunk_tokens": 12000,
            "max_chunks": 4,
            "min_files_per_chunk": 2,
            "include_file_classes": ["reviewable", "config_only"],
            "max_total_prompt_tokens": 90000,
            "max_latency_seconds": 180,
            "output_headroom_tokens": 3000,
        }
    )
    assert chunking.enabled is True
    assert chunking.proactive_threshold_tokens == 31000
    assert chunking.target_chunk_tokens == 12000
    assert chunking.max_chunks == 4
    assert chunking.min_files_per_chunk == 2
    assert chunking.include_file_classes == ["reviewable", "config_only"]
    assert chunking.max_total_prompt_tokens == 90000
    assert chunking.max_latency_seconds == 180
    assert chunking.output_headroom_tokens == 3000


class FakeGitHubClient:
    def __init__(self, files: dict[str, str]):
        self.files = files

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        if path not in self.files:
            request = httpx.Request("GET", f"https://example.com/{owner}/{repo}/{path}")
            response = httpx.Response(status_code=404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        return self.files[path]


def test_load_review_config_uses_defaults_when_file_missing() -> None:
    config = asyncio.run(load_review_config(FakeGitHubClient({}), "acme", "demo", "sha"))
    assert config.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD
    assert config.prompt_additions is None


def test_load_review_config_reads_threshold_and_prompt_additions() -> None:
    config = asyncio.run(
        load_review_config(
            FakeGitHubClient(
                {
                    ".codereview.yml": """
                    confidence_threshold: 0.9
                    prompt_additions: |
                      This repo uses generated types.
                    """
                }
            ),
            "acme",
            "demo",
            "sha",
        )
    )
    assert config.confidence_threshold == 90
    assert config.prompt_additions == "This repo uses generated types."


def test_load_review_config_reads_new_phase4_fields() -> None:
    config = asyncio.run(
        load_review_config(
            FakeGitHubClient(
                {
                    ".codereview.yml": """
                    severity_threshold: high
                    categories:
                      - security
                      - correctness
                    ignore_paths:
                      - "**/*.md"
                    review_drafts: true
                    max_findings_per_pr: 7
                    """
                }
            ),
            "acme",
            "demo",
            "sha",
        )
    )
    assert config.severity_threshold == "high"
    assert config.categories == ["security", "correctness"]
    assert config.ignore_paths == ["**/*.md"]
    assert config.review_drafts is True
    assert config.max_findings_per_pr == 7


def test_load_review_config_reads_chunking_block() -> None:
    config = asyncio.run(
        load_review_config(
            FakeGitHubClient(
                {
                    ".codereview.yml": """
                    chunking:
                      enabled: true
                      proactive_threshold_tokens: 32000
                      target_chunk_tokens: 15000
                      max_chunks: 6
                      include_file_classes:
                        - reviewable
                        - config_only
                    """
                }
            ),
            "acme",
            "demo",
            "sha",
        )
    )
    assert config.chunking.enabled is True
    assert config.chunking.proactive_threshold_tokens == 32000
    assert config.chunking.target_chunk_tokens == 15000
    assert config.chunking.max_chunks == 6
    assert config.chunking.include_file_classes == ["reviewable", "config_only"]


def test_load_review_config_reads_models_routing_block() -> None:
    config = asyncio.run(
        load_review_config(
            FakeGitHubClient(
                {
                    ".codereview.yml": """
                    models:
                      policy: balanced
                      provider_order:
                        - openai
                        - anthropic
                      roles:
                        fast_path:
                          tier: economy
                        challenger:
                          tier: frontier
                          require_provider_diversity: true
                      allow_auto_fallback: true
                      allow_default_model_promotion: false
                    """
                }
            ),
            "acme",
            "demo",
            "sha",
        )
    )
    assert config.models.provider_order == ["openai", "anthropic"]
    assert config.models.roles["fast_path"].tier == "economy"
    assert config.models.roles["challenger"].require_provider_diversity is True


def test_parse_model_config_provider_defaults_to_anthropic() -> None:
    model = _parse_model_config({"provider": "bogus", "name": "model-x"})
    assert model.provider == "anthropic"


def test_parse_max_mode_reads_challenger_and_tie_break() -> None:
    max_mode = _parse_max_mode(
        {
            "enabled": True,
            "conflict_threshold": 42,
            "high_risk_severity": "critical",
            "challenger": {"provider": "openai", "name": "gpt-5.5"},
            "tie_break": {"provider": "gemini", "name": "gemini-2.5-pro"},
        }
    )
    assert max_mode.enabled is True
    assert max_mode.conflict_threshold == 42
    assert max_mode.high_risk_severity == "critical"
    assert max_mode.challenger_provider == "openai"
    assert max_mode.tie_break_provider == "gemini"
