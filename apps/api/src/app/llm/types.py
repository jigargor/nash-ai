from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ModelProvider = str
ModelTier = Literal["frontier", "balanced", "economy", "fallback"]
ModelStatus = Literal["active", "legacy", "deprecated", "retired", "unknown"]
PromptCachingStrategy = Literal[
    "none", "explicit_breakpoint", "automatic_prefix", "implicit", "explicit_cached_content"
]


class ModelCapabilities(BaseModel):
    tool_calling: bool = False
    structured_output: bool = False
    prompt_caching: PromptCachingStrategy = "none"
    max_context_tokens: int = Field(default=0, ge=0)


class ModelPricing(BaseModel):
    input_per_1m: Decimal | None = None
    cached_input_per_1m: Decimal | None = None
    output_per_1m: Decimal | None = None

    @field_validator("input_per_1m", "cached_input_per_1m", "output_per_1m", mode="before")
    @classmethod
    def normalize_decimal(cls, value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        decimal_value = Decimal(str(value))
        return decimal_value if decimal_value >= 0 else None


class ModelSources(BaseModel):
    models_url: str | None = None
    deprecations_url: str | None = None
    pricing_url: str | None = None
    caching_url: str | None = None


class ModelRecord(BaseModel):
    provider: ModelProvider
    model: str
    family: str
    tier: ModelTier
    status: ModelStatus = "unknown"
    replacement_candidates: list[str] = Field(default_factory=list)
    shutdown_at: datetime | None = None
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    pricing: ModelPricing = Field(default_factory=ModelPricing)
    sources: ModelSources = Field(default_factory=ModelSources)
    score: int = 50

    @field_validator("provider", "model", "family")
    @classmethod
    def non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must be non-empty")
        return normalized

    @model_validator(mode="after")
    def retired_models_need_replacements(self) -> "ModelRecord":
        if self.status == "retired" and not self.replacement_candidates:
            raise ValueError("retired models must provide replacement_candidates")
        return self


class ProviderRecord(BaseModel):
    provider: ModelProvider
    display_name: str
    status: Literal["active", "sunsetting", "disabled"] = "active"
    api_key_setting: str
    default_cache_strategy: PromptCachingStrategy = "none"
    docs: ModelSources = Field(default_factory=ModelSources)


class ModelCatalog(BaseModel):
    version: int = 1
    generated_at: datetime | None = None
    providers: list[ProviderRecord]
    models: list[ModelRecord]

    def provider_ids(self) -> set[str]:
        return {provider.provider for provider in self.providers}

    def active_provider_ids(self) -> set[str]:
        return {provider.provider for provider in self.providers if provider.status == "active"}

    def find_model(self, provider: str, model: str) -> ModelRecord | None:
        for record in self.models:
            if record.provider == provider and record.model == model:
                return record
        return None

    def models_for_provider(self, provider: str) -> list[ModelRecord]:
        return [record for record in self.models if record.provider == provider]


class LLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    provider_usage: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_total(self) -> "LLMUsage":
        if self.total_tokens <= 0:
            self.total_tokens = self.input_tokens + self.output_tokens
        return self


class ProviderHealthCheck(BaseModel):
    provider: ModelProvider
    model: str
    ok: bool
    latency_ms: int | None = None
    failure_class: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
