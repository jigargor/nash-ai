"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useUsageSummary } from "@/hooks/use-usage-summary";
import { useInstallations } from "@/hooks/use-installations";

type CapViewMode = "per_key" | "cumulative";

function formatUsd(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "$0.00";
  return `$${numeric.toFixed(4)}`;
}

export default function DashboardHomePage() {
  const installations = useInstallations();
  const activeInstallations = installations.data?.filter((installation) => installation.active) ?? [];
  const installationId = activeInstallations[0]?.installation_id;
  const usageSummary = useUsageSummary(installationId);
  const [capViewMode, setCapViewMode] = useState<CapViewMode>("per_key");
  const [selectedProviders, setSelectedProviders] = useState<string[]>([]);
  const dailyUsageRequests = usageSummary.data?.daily_requests.at(-1)?.requests ?? 0;
  const weeklyUsageRequests = usageSummary.data?.weekly_requests.at(-1)?.requests ?? 0;
  const capState = usageSummary.data?.cumulative_caps.state ?? "safe";
  const capLabel =
    capState === "capped" ? "Cap reached" : capState === "near-cap" ? "Near cap" : "Within cap";
  const perKeyCaps = usageSummary.data?.api_key_caps ?? [];
  const configuredProviderCount = usageSummary.data?.configured_provider_count ?? 0;
  const cumulativeCaps = usageSummary.data?.cumulative_caps;

  const selectedCapRows = useMemo(() => {
    if (capViewMode !== "cumulative") return [];
    return perKeyCaps.filter((row) => selectedProviders.includes(row.provider));
  }, [capViewMode, perKeyCaps, selectedProviders]);

  const combinationTotals = useMemo(() => {
    const dailyTokens = selectedCapRows.reduce((sum, row) => sum + row.daily_tokens, 0);
    const weeklyTokens = selectedCapRows.reduce((sum, row) => sum + row.weekly_tokens, 0);
    const dailyCost = selectedCapRows.reduce((sum, row) => sum + Number(row.daily_cost_usd), 0);
    const weeklyCost = selectedCapRows.reduce((sum, row) => sum + Number(row.weekly_cost_usd), 0);
    return { dailyTokens, weeklyTokens, dailyCost, weeklyCost };
  }, [selectedCapRows]);

  function toggleProvider(provider: string): void {
    setSelectedProviders((previous) =>
      previous.includes(provider) ? previous.filter((item) => item !== provider) : [...previous, provider],
    );
  }

  useEffect(() => {
    if (capViewMode !== "cumulative") return;
    setSelectedProviders((previous) => {
      if (perKeyCaps.length === 0) return previous;
      if (previous.length > 0) return previous;
      return perKeyCaps.map((row) => row.provider);
    });
  }, [capViewMode, perKeyCaps]);

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      <div className="metrics-grid">
        <article className="metric-card">
          <p className="metric-label">Providers with API keys</p>
          <p className="metric-value">{configuredProviderCount}</p>
          <p className="metric-label" style={{ marginTop: "0.35rem", fontSize: "0.75rem", opacity: 0.85 }}>
            With token usage in table (24h window): {perKeyCaps.length}
          </p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Service requests (24h)</p>
          <p className="metric-value">{dailyUsageRequests}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Service requests (7d)</p>
          <p className="metric-value">{weeklyUsageRequests}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Session cap</p>
          <p className="metric-value">{capLabel}</p>
        </article>
      </div>

      <Panel elevated>
        <h1 style={{ marginTop: 0, marginBottom: "0.4rem", fontFamily: "var(--font-instrument-serif)" }}>
          API Key Cap Controls
        </h1>
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          View caps per key, cumulative across all keys, or a custom combination.
        </p>
        {usageSummary.isLoading || installations.isLoading ? (
          <StateBlock title="Loading cap telemetry" description="Fetching usage + cap data." />
        ) : null}

        {usageSummary.isError || installations.isError ? (
          <StateBlock title="Failed to load cap telemetry" description="Retry once the API becomes available." />
        ) : null}

        {!installations.isLoading && !installations.isError && !installationId ? (
          <StateBlock
            title="No installations connected"
            description="Install the GitHub App to start receiving usage telemetry."
            action={
              <a
                className="button button-primary"
                href="https://github.com/settings/apps"
                target="_blank"
                rel="noreferrer"
              >
                Install GitHub App
              </a>
            }
          />
        ) : null}

        {!usageSummary.isLoading && !usageSummary.isError ? (
          <div style={{ display: "grid", gap: "0.7rem" }}>
            <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>
              <button
                type="button"
                className={`button ${capViewMode === "per_key" ? "button-primary" : "button-ghost"}`}
                onClick={() => setCapViewMode("per_key")}
              >
                By API Key
              </button>
              <button
                type="button"
                className={`button ${capViewMode === "cumulative" ? "button-primary" : "button-ghost"}`}
                onClick={() => setCapViewMode("cumulative")}
              >
                Cumulative
              </button>
            </div>

            {capViewMode === "per_key" ? (
              <div style={{ display: "grid", gap: "0.45rem" }}>
                {perKeyCaps.length === 0 ? (
                  <StateBlock title="No API key usage yet" description="Run reviews to populate provider cap telemetry." />
                ) : (
                  perKeyCaps.map((row) => (
                    <article
                      key={row.provider}
                      style={{
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius-md)",
                        padding: "0.6rem 0.75rem",
                        display: "grid",
                        gap: "0.25rem",
                      }}
                    >
                      <strong>{row.provider}</strong>
                      <span style={{ color: "var(--text-muted)" }}>
                        Daily: {row.daily_tokens} tokens ({formatUsd(row.daily_cost_usd)}) / cap {row.effective_cap_tokens}
                      </span>
                      <span style={{ color: "var(--text-muted)" }}>
                        Weekly: {row.weekly_tokens} tokens ({formatUsd(row.weekly_cost_usd)})
                      </span>
                    </article>
                  ))
                )}
              </div>
            ) : null}

            {capViewMode === "cumulative" && cumulativeCaps ? (
              <div style={{ display: "grid", gap: "0.55rem" }}>
                <article
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-md)",
                    padding: "0.7rem 0.8rem",
                    display: "grid",
                    gap: "0.25rem",
                  }}
                >
                  <strong>Cumulative usage across all API keys</strong>
                  <span style={{ color: "var(--text-muted)" }}>
                    Daily: {cumulativeCaps.daily_tokens} / {cumulativeCaps.daily_token_budget} tokens
                  </span>
                  <span style={{ color: "var(--text-muted)" }}>
                    Weekly: {cumulativeCaps.weekly_tokens} tokens · state: {cumulativeCaps.state}
                  </span>
                </article>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                  {perKeyCaps.map((row) => (
                    <label
                      key={row.provider}
                      style={{
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius-md)",
                        padding: "0.35rem 0.55rem",
                        display: "inline-flex",
                        gap: "0.35rem",
                        alignItems: "center",
                        color: "var(--text-muted)",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={selectedProviders.includes(row.provider)}
                        onChange={() => toggleProvider(row.provider)}
                      />
                      <span>{row.provider}</span>
                    </label>
                  ))}
                </div>
                <article
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-md)",
                    padding: "0.6rem 0.75rem",
                    display: "grid",
                    gap: "0.25rem",
                  }}
                >
                  <strong>Selected API key combination</strong>
                  <span style={{ color: "var(--text-muted)" }}>
                    Daily: {combinationTotals.dailyTokens} tokens ({formatUsd(String(combinationTotals.dailyCost))})
                  </span>
                  <span style={{ color: "var(--text-muted)" }}>
                    Weekly: {combinationTotals.weeklyTokens} tokens ({formatUsd(String(combinationTotals.weeklyCost))})
                  </span>
                  <span style={{ color: "var(--text-muted)" }}>
                    Compared against daily shared cap: {usageSummary.data?.cumulative_caps?.daily_token_budget ?? 0} tokens
                  </span>
                </article>
              </div>
            ) : null}
          </div>
        ) : null}
      </Panel>

      <Panel>
        <h2 style={{ marginTop: 0, marginBottom: "0.45rem" }}>Evaluate External</h2>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          Run critical-only analysis on a public GitHub repository with cost controls and staged execution.
        </p>
        <div style={{ marginTop: "0.75rem" }}>
          <Link href="/evaluate-external" className="button button-primary">
            Open Evaluate External
          </Link>
        </div>
      </Panel>
    </section>
  );
}
