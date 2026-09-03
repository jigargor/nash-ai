"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { collectDropBuckets } from "@/lib/api/quality";

interface DropReasonPanelProps {
  debugArtifacts: Record<string, unknown> | null | undefined;
  generatedFindings?: number | null;
  postedFindings: number;
}

const REASON_HELP: Record<string, string> = {
  target_line_mismatch: "The quoted line did not match the file at HEAD, so GitHub could not anchor it.",
  line_out_of_range: "Line number is outside the file.",
  line_not_in_diff: "Line is not part of the PR diff; GitHub rejects inline comments there (422).",
  file_not_in_context: "File was not fetched into the review context.",
  syntax_invalid_suggestion: "Applying the suggestion produced code that does not parse.",
  incoherent_suggestion: "Suggestion is a no-op, too long (>20 lines), or does not replace the target lines.",
  validator_error: "Validator raised; the finding was withheld instead of failing the review.",
  below_confidence_threshold: "Model confidence was below the repository threshold.",
  evidence_rejected: "Claimed tool/fact evidence did not match the actual tool trace.",
  duplicate: "Near-duplicate of another finding on the same lines.",
  delivery_rejected: "GitHub rejected this comment; the rest of the review was posted.",
  editor_dropped: "Editor stage removed it (acknowledged in PR text, prior review, or TODO).",
};

export function DropReasonPanel({ debugArtifacts, generatedFindings, postedFindings }: DropReasonPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const buckets = useMemo(() => collectDropBuckets(debugArtifacts), [debugArtifacts]);
  const dropped = buckets.reduce((sum, bucket) => sum + bucket.count, 0);
  if (dropped === 0) return null;
  const generated = typeof generatedFindings === "number" ? generatedFindings : postedFindings + dropped;

  return (
    <Panel aria-label="Dropped findings">
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <div>
          <h3 style={{ margin: 0 }}>Withheld findings</h3>
          <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {generated} generated · {postedFindings} posted · {dropped} withheld by validation, policy, or delivery.
          </p>
        </div>
        <Button variant="ghost" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
          {expanded ? "Hide details" : "Show details"}
        </Button>
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: "0.75rem 0 0", display: "grid", gap: "0.5rem" }}>
        {buckets.map((bucket) => (
          <li key={bucket.key} style={{ border: "1px solid var(--border)", borderRadius: "0.5rem", padding: "0.55rem 0.7rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
              <span>
                <code>{bucket.stage}</code> · <strong>{bucket.reason}</strong>
              </span>
              <span style={{ color: "var(--text-muted)" }}>{bucket.count}</span>
            </div>
            <p style={{ margin: "0.3rem 0 0", color: "var(--text-muted)", fontSize: "0.85rem" }}>
              {REASON_HELP[bucket.reason] ?? "Removed by a pipeline stage."}
            </p>
            {expanded && bucket.samples.length > 0 ? (
              <ul style={{ margin: "0.4rem 0 0", paddingLeft: "1rem", fontSize: "0.82rem", fontFamily: "var(--font-geist-mono)" }}>
                {bucket.samples.map((sample, index) => (
                  <li key={`${bucket.key}-${index}`} style={{ overflowWrap: "anywhere" }}>
                    {sample.file_path ? `${sample.file_path}:${sample.line_start}` : "(no anchor)"}
                    {sample.detail ? ` — ${sample.detail}` : ""}
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
