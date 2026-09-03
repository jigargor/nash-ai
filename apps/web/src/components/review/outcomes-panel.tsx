"use client";

import type { FindingOutcome, FindingOutcomeValue } from "@ai-code-review/shared-types";
import { OUTCOME_EVENTS } from "@ai-code-review/shared-types";

import { Panel } from "@/components/ui/panel";

interface OutcomesPanelProps {
  findingOutcomes: FindingOutcome[];
  postedFindings: number;
}

const OUTCOME_ORDER: FindingOutcomeValue[] = [
  "applied_directly",
  "applied_modified",
  "acknowledged",
  "dismissed",
  "ignored",
  "abandoned",
  "superseded",
  "pending",
];

const OUTCOME_LABEL: Record<FindingOutcomeValue, string> = {
  applied_directly: "Suggestion accepted",
  applied_modified: "Suggestion edited then applied",
  acknowledged: "Resolved by the author",
  dismissed: "Dismissed",
  ignored: "Ignored (PR closed without change)",
  abandoned: "Abandoned",
  superseded: "Superseded by a later run",
  pending: "Pending (PR still open)",
};

function percent(numerator: number, denominator: number): string {
  if (!denominator) return "–";
  return `${Math.round((numerator / denominator) * 100)}%`;
}

export function OutcomesPanel({ findingOutcomes, postedFindings }: OutcomesPanelProps) {
  if (postedFindings === 0 && findingOutcomes.length === 0) return null;
  const counts = new Map<FindingOutcomeValue, number>();
  for (const outcome of findingOutcomes) {
    counts.set(outcome.outcome, (counts.get(outcome.outcome) ?? 0) + 1);
  }
  const classified = findingOutcomes.filter((item) => item.outcome !== "pending").length;
  const accepted = (counts.get("applied_directly") ?? 0) + (counts.get("applied_modified") ?? 0);
  const resolved = accepted + (counts.get("acknowledged") ?? 0);
  const dismissed = counts.get("dismissed") ?? 0;

  return (
    <Panel aria-label="Finding outcomes">
      <h3 style={{ marginTop: 0 }}>Outcomes</h3>
      <div className="metrics-grid">
        <article className="metric-card">
          <p className="metric-label">Suggestions accepted</p>
          <p className="metric-value">{percent(accepted, classified)}</p>
          <p className="metric-label" style={{ fontSize: "0.75rem", opacity: 0.85 }}>
            {accepted} of {classified} classified
          </p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Findings resolved</p>
          <p className="metric-value">{percent(resolved, classified)}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Dismissed</p>
          <p className="metric-value">{percent(dismissed, classified)}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Pending</p>
          <p className="metric-value">{counts.get("pending") ?? Math.max(postedFindings - findingOutcomes.length, 0)}</p>
        </article>
      </div>
      <table style={{ width: "100%", marginTop: "0.75rem", fontSize: "0.88rem", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--text-muted)" }}>
            <th style={{ padding: "0.25rem 0" }}>Outcome</th>
            <th>Telemetry event</th>
            <th style={{ textAlign: "right" }}>Count</th>
          </tr>
        </thead>
        <tbody>
          {OUTCOME_ORDER.filter((value) => (counts.get(value) ?? 0) > 0).map((value) => (
            <tr key={value} style={{ borderTop: "1px solid var(--border)" }}>
              <td style={{ padding: "0.3rem 0" }}>{OUTCOME_LABEL[value]}</td>
              <td>
                <code>{OUTCOME_EVENTS[value] ?? "—"}</code>
              </td>
              <td style={{ textAlign: "right" }}>{counts.get(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
