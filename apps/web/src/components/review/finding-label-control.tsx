"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useLabelFinding } from "@/hooks/use-finding-labels";
import { FINDING_LABEL_VALUES, type FindingLabelValue } from "@/lib/api/quality";

interface FindingLabelControlProps {
  reviewId: number;
  findingIndex: number;
  currentLabel?: string | null;
}

const LABEL_TEXT: Record<FindingLabelValue, string> = {
  true_positive: "True positive",
  false_positive: "False positive",
  severity_wrong: "Severity wrong",
  category_wrong: "Category wrong",
  duplicate: "Duplicate",
  not_actionable: "Not actionable",
  correct_but_too_minor: "Correct but too minor",
  accepted: "Accepted",
  accepted_with_modification: "Accepted with modification",
};

function isLabelValue(value: string): value is FindingLabelValue {
  return (FINDING_LABEL_VALUES as readonly string[]).includes(value);
}

export function FindingLabelControl({ reviewId, findingIndex, currentLabel }: FindingLabelControlProps) {
  const [selected, setSelected] = useState<string>(currentLabel ?? "");
  const labelMutation = useLabelFinding();
  const selectId = `finding-label-${reviewId}-${findingIndex}`;
  const isDirty = selected !== (currentLabel ?? "") && isLabelValue(selected);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
      <label htmlFor={selectId} style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
        Label
      </label>
      <select
        id={selectId}
        value={selected}
        onChange={(event) => setSelected(event.target.value)}
        style={{ fontSize: "0.82rem", padding: "0.2rem 0.35rem", borderRadius: "0.35rem", border: "1px solid var(--border)", background: "var(--card)", color: "inherit" }}
      >
        <option value="">Unlabelled</option>
        {FINDING_LABEL_VALUES.map((value) => (
          <option key={value} value={value}>
            {LABEL_TEXT[value]}
          </option>
        ))}
      </select>
      <Button
        variant="ghost"
        disabled={!isDirty || labelMutation.isPending}
        onClick={() => {
          if (!isLabelValue(selected)) return;
          labelMutation.mutate({ reviewId, findingIndex, label: selected });
        }}
      >
        {labelMutation.isPending ? "Saving…" : "Save label"}
      </Button>
      {labelMutation.isError ? (
        <span style={{ fontSize: "0.78rem", color: "var(--severity-critical)" }}>
          {labelMutation.error instanceof Error ? labelMutation.error.message : "Unable to save label."}
        </span>
      ) : null}
      {labelMutation.isSuccess && !isDirty ? (
        <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>Saved</span>
      ) : null}
    </div>
  );
}
