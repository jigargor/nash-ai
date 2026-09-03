"use client";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useOutcomeSummary } from "@/hooks/use-outcome-summary";
import { useCostPerFinding, useScorecard } from "@/hooks/use-scorecard";

interface OutcomeScorecardProps {
  installationId?: number;
  repoFullName?: string;
}

function percent(value: number | undefined | null): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "–";
  return `${Math.round(value * 100)}%`;
}

function usd(value: number | null | undefined, digits = 2): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "–";
  return `$${value.toFixed(digits)}`;
}

export function OutcomeScorecard({ installationId, repoFullName }: OutcomeScorecardProps) {
  const outcomes = useOutcomeSummary(installationId, repoFullName);
  const scorecard = useScorecard(installationId, repoFullName);
  const cost = useCostPerFinding(installationId);

  if (installationId === undefined) {
    return (
      <Panel aria-label="Review scorecard">
        <h3 style={{ marginTop: 0 }}>Review scorecard</h3>
        <StateBlock title="No installation selected" description="Install the GitHub App on a repository to start tracking review outcomes." />
      </Panel>
    );
  }

  const metrics = outcomes.data?.global_metrics;
  const classified = outcomes.data?.total_classified ?? 0;
  const counts = outcomes.data?.outcomes ?? {};
  const accepted = (counts.applied_directly ?? 0) + (counts.applied_modified ?? 0);

  return (
    <Panel aria-label="Review scorecard">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.5rem" }}>
        <h3 style={{ margin: 0 }}>Review scorecard{repoFullName ? ` · ${repoFullName}` : ""}</h3>
        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          {classified} classified finding{classified === 1 ? "" : "s"} · last {scorecard.data?.window_days ?? 14} days
        </span>
      </div>
      {outcomes.isError ? (
        <StateBlock title="Outcome data unavailable" description="The telemetry API did not return an outcome summary." />
      ) : (
        <div className="metrics-grid" style={{ marginTop: "0.75rem" }}>
          <article className="metric-card">
            <p className="metric-label">Suggestions accepted</p>
            <p className="metric-value">{percent(classified ? accepted / classified : undefined)}</p>
            <p className="metric-label" style={{ fontSize: "0.75rem", opacity: 0.85 }}>
              {counts.applied_directly ?? 0} as-is · {counts.applied_modified ?? 0} edited
            </p>
          </article>
          <article className="metric-card">
            <p className="metric-label">Useful rate</p>
            <p className="metric-value">{percent(metrics?.useful_rate)}</p>
            <p className="metric-label" style={{ fontSize: "0.75rem", opacity: 0.85 }}>
              accepted + acknowledged
            </p>
          </article>
          <article className="metric-card">
            <p className="metric-label">Dismissed</p>
            <p className="metric-value">{percent(metrics?.dismiss_rate)}</p>
          </article>
          <article className="metric-card">
            <p className="metric-label">Ignored</p>
            <p className="metric-value">{percent(metrics?.ignore_rate)}</p>
          </article>
          <article className="metric-card">
            <p className="metric-label">Cost per accepted finding</p>
            <p className="metric-value">{usd(cost.data?.summary.overall_cost_per_tp_usd)}</p>
            <p className="metric-label" style={{ fontSize: "0.75rem", opacity: 0.85 }}>
              {cost.data ? `${usd(cost.data.summary.total_cost_usd)} over ${cost.data.summary.reviews_analyzed} reviews` : "–"}
            </p>
          </article>
          <article className="metric-card">
            <p className="metric-label">Fast-path skip/light rate</p>
            <p className="metric-value">{percent(scorecard.data?.fast_path_accept_rate)}</p>
            <p className="metric-label" style={{ fontSize: "0.75rem", opacity: 0.85 }}>
              debate disagreement {percent(scorecard.data?.disagreement_rate)}
            </p>
          </article>
        </div>
      )}
    </Panel>
  );
}
