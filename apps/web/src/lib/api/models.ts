import { apiFetch } from "@/lib/api/client";

export interface ModelCatalogSourceLinks {
  models_url: string | null;
  deprecations_url: string | null;
  pricing_url: string | null;
  caching_url: string | null;
}

export interface ModelCatalogProvider {
  provider: string;
  display_name: string;
  status: "active" | "sunsetting" | "disabled";
  api_key_setting: string;
  default_cache_strategy: string;
  docs: ModelCatalogSourceLinks;
}

export interface ModelCatalogPricing {
  input_per_1m: string | null;
  cached_input_per_1m: string | null;
  output_per_1m: string | null;
}

export interface ModelCatalogCapabilities {
  tool_calling: boolean;
  structured_output: boolean;
  prompt_caching: string;
  max_context_tokens: number;
}

export interface ModelCatalogModel {
  provider: string;
  model: string;
  family: string;
  tier: "frontier" | "balanced" | "economy" | "fallback";
  status: "active" | "legacy" | "deprecated" | "retired" | "unknown";
  replacement_candidates: string[];
  shutdown_at: string | null;
  capabilities: ModelCatalogCapabilities;
  pricing: ModelCatalogPricing;
  sources: ModelCatalogSourceLinks;
  score: number;
}

export interface ModelCatalogPayload {
  version: number;
  generated_at: string | null;
  providers: ModelCatalogProvider[];
  models: ModelCatalogModel[];
}

export interface ModelsCatalogResponse {
  version: number;
  catalog_hash: string;
  sources_note: string;
  catalog: ModelCatalogPayload;
}

export function fetchModelsCatalog() {
  return apiFetch<ModelsCatalogResponse>("/api/v1/models/catalog");
}
