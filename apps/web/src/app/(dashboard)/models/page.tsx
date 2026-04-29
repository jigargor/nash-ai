"use client";

import { useMemo, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useModelsCatalog } from "@/hooks/use-models-catalog";
import type { ModelCatalogModel } from "@/lib/api/models";

function formatPrice(value: string | null): string {
  if (!value) return "Unknown";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "Unknown";
  return `$${numeric.toFixed(3)} / 1M`;
}

function compareModels(left: ModelCatalogModel, right: ModelCatalogModel): number {
  return left.model.localeCompare(right.model);
}

function matchesQuery(model: ModelCatalogModel, query: string): boolean {
  if (!query) return true;
  const haystack = [
    model.provider,
    model.model,
    model.family,
    model.tier,
    model.status,
    ...model.replacement_candidates,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

export default function ModelsPage() {
  const modelsCatalog = useModelsCatalog();
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const groupedByProvider = useMemo(() => {
    const providerMap = new Map<string, ModelCatalogModel[]>();
    const models = modelsCatalog.data?.catalog.models ?? [];
    for (const model of models) {
      if (!matchesQuery(model, normalizedQuery)) continue;
      const existing = providerMap.get(model.provider);
      if (existing) {
        existing.push(model);
        continue;
      }
      providerMap.set(model.provider, [model]);
    }
    return providerMap;
  }, [modelsCatalog.data?.catalog.models, normalizedQuery]);

  if (modelsCatalog.isLoading) {
    return <StateBlock title="Loading models catalog" description="Fetching provider and model pricing information." />;
  }

  if (modelsCatalog.isError || !modelsCatalog.data) {
    return <StateBlock title="Failed to load models catalog" description="Retry after API connectivity is restored." />;
  }

  const providers = modelsCatalog.data.catalog.providers;
  const totalVisible = Array.from(groupedByProvider.values()).reduce(
    (count, rows) => count + rows.length,
    0,
  );

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      <Panel elevated>
        <h1 style={{ marginTop: 0, marginBottom: "0.4rem", fontFamily: "var(--font-instrument-serif)" }}>Models</h1>
        <p style={{ marginTop: 0, color: "var(--text-muted)" }}>
          Provider model inventory with current baseline cost data. Prices are shown in USD per 1M tokens.
        </p>
        <div style={{ display: "grid", gap: "0.55rem", marginTop: "0.65rem" }}>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search provider/model/family/tier/status… (e.g. flash-lite, haiku, economy)"
            aria-label="Search model catalog"
            style={{
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)",
              background: "var(--card)",
              color: "var(--text-primary)",
              padding: "0.55rem 0.7rem",
              fontSize: "0.9rem",
            }}
          />
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.82rem" }}>
            Showing {totalVisible} model{totalVisible === 1 ? "" : "s"}.
          </p>
        </div>
        <p style={{ marginTop: 0, color: "var(--text-muted)", fontSize: "0.85rem" }}>{modelsCatalog.data.sources_note}</p>
      </Panel>

      {providers.map((provider) => {
        const models = [...(groupedByProvider.get(provider.provider) ?? [])].sort(compareModels);
        return (
          <Panel key={provider.provider}>
            <div style={{ display: "grid", gap: "0.6rem" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.6rem" }}>
                <h2 style={{ margin: 0 }}>{provider.display_name}</h2>
                <span className="status-pill">{provider.status}</span>
              </div>
              <div style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                API key setting: <code>{provider.api_key_setting}</code>
              </div>
              {models.length === 0 ? (
                <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.85rem" }}>
                  No catalog rows match this search for {provider.display_name}.
                </p>
              ) : (
                <div style={{ display: "grid", gap: "0.45rem" }}>
                  {models.map((model) => (
                    <article
                      key={`${model.provider}:${model.model}`}
                      style={{
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius-md)",
                        padding: "0.65rem 0.75rem",
                        display: "grid",
                        gap: "0.2rem",
                      }}
                    >
                      <strong>{model.model}</strong>
                      <span style={{ color: "var(--text-muted)" }}>
                        Family: {model.family} · Tier: {model.tier} · Status: {model.status}
                      </span>
                      {model.replacement_candidates.length > 0 ? (
                        <span style={{ color: "var(--text-muted)" }}>
                          Variants/replacements: {model.replacement_candidates.join(", ")}
                        </span>
                      ) : null}
                      <span style={{ color: "var(--text-muted)" }}>
                        Input: {formatPrice(model.pricing.input_per_1m)} · Cached:{" "}
                        {formatPrice(model.pricing.cached_input_per_1m)} · Output:{" "}
                        {formatPrice(model.pricing.output_per_1m)}
                      </span>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </Panel>
        );
      })}
    </section>
  );
}
