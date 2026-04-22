"use client";

import type { Finding, FindingOutcome } from "@ai-code-review/shared-types";

import { useReviewUiStore } from "@/stores/review-ui-store";

interface FindingsPanelProps {
  findings: Finding[];
  findingOutcomes: FindingOutcome[];
  selectedFindingIndex: number | null;
  onSelectFinding: (index: number) => void;
  onDismiss: (index: number) => void;
  onCopySuggestion: (index: number) => void;
}

export function FindingsPanel({
  findings,
  findingOutcomes,
  selectedFindingIndex,
  onSelectFinding,
  onDismiss,
  onCopySuggestion,
}: FindingsPanelProps) {
  const severityFilters = useReviewUiStore((state) => state.severityFilters);
  const categoryFilters = useReviewUiStore((state) => state.categoryFilters);
  const toggleSeverityFilter = useReviewUiStore((state) => state.toggleSeverityFilter);
  const toggleCategoryFilter = useReviewUiStore((state) => state.toggleCategoryFilter);

  const hasSeverityFilters = Object.values(severityFilters).some(Boolean);
  const hasCategoryFilters = Object.values(categoryFilters).some(Boolean);

  const visibleFindings = findings
    .map((finding, index) => ({ finding, index }))
    .filter(({ finding }) => {
      const severityAllowed = !hasSeverityFilters || Boolean(severityFilters[finding.severity]);
      const categoryAllowed = !hasCategoryFilters || Boolean(categoryFilters[finding.category]);
      return severityAllowed && categoryAllowed;
    });

  const severities = [...new Set(findings.map((finding) => finding.severity))];
  const categories = [...new Set(findings.map((finding) => finding.category))];

  return (
    <section style={{ borderLeft: "1px solid var(--border)", padding: "0.75rem", overflowY: "auto" }}>
      <h3 style={{ marginTop: 0 }}>Findings</h3>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginBottom: "0.6rem" }}>
        {severities.map((severity) => (
          <button
            key={severity}
            type="button"
            onClick={() => toggleSeverityFilter(severity)}
            style={{
              border: "1px solid var(--border)",
              borderRadius: "999px",
              background: severityFilters[severity] ? "rgba(245, 158, 11, 0.3)" : "transparent",
              color: "inherit",
              padding: "0.2rem 0.6rem",
            }}
          >
            {severity}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginBottom: "0.8rem" }}>
        {categories.map((category) => (
          <button
            key={category}
            type="button"
            onClick={() => toggleCategoryFilter(category)}
            style={{
              border: "1px solid var(--border)",
              borderRadius: "999px",
              background: categoryFilters[category] ? "rgba(245, 158, 11, 0.3)" : "transparent",
              color: "inherit",
              padding: "0.2rem 0.6rem",
            }}
          >
            {category}
          </button>
        ))}
      </div>

      {visibleFindings.map(({ finding, index }) => (
        <article
          key={`${finding.file_path}-${finding.line_start}-${index}`}
          data-selected={selectedFindingIndex === index}
          style={{
            border: "1px solid var(--border)",
            borderRadius: "0.5rem",
            padding: "0.6rem",
            marginBottom: "0.5rem",
            background: selectedFindingIndex === index ? "rgba(245, 158, 11, 0.2)" : "var(--card)",
          }}
        >
          <button
            type="button"
            onClick={() => onSelectFinding(index)}
            style={{ background: "transparent", border: "none", color: "inherit", width: "100%", textAlign: "left" }}
          >
            <strong>
              {finding.severity.toUpperCase()} · {finding.category}
            </strong>
            <div style={{ marginTop: "0.25rem" }}>{finding.message}</div>
            <div style={{ marginTop: "0.25rem", color: "var(--text-muted)" }}>
              {finding.file_path}:{finding.line_start}
            </div>
            <div style={{ marginTop: "0.25rem", color: "var(--text-muted)" }}>
              Outcome: {findingOutcomes.find((item) => item.finding_index === index)?.outcome ?? "pending"}
            </div>
          </button>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button
              type="button"
              onClick={() => onCopySuggestion(index)}
              style={{
                border: "1px solid var(--border)",
                borderRadius: "0.375rem",
                background: "transparent",
                color: "inherit",
                padding: "0.25rem 0.5rem",
              }}
            >
              Copy suggestion
            </button>
            <button
              type="button"
              onClick={() => onDismiss(index)}
              style={{
                border: "1px solid var(--border)",
                borderRadius: "0.375rem",
                background: "transparent",
                color: "inherit",
                padding: "0.25rem 0.5rem",
              }}
            >
              Dismiss
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}
