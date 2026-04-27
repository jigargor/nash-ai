"use client";

import type { Finding, FindingOutcome } from "@ai-code-review/shared-types";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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

  function severityVariant(value: Finding["severity"]): "critical" | "high" | "medium" | "low" | "info" {
    if (value === "critical" || value === "high" || value === "medium" || value === "low") return value;
    return "info";
  }

  return (
    <section style={{ borderLeft: "1px solid var(--border)", padding: "0.75rem", overflowY: "auto" }}>
      <h3 style={{ marginTop: 0 }}>Findings</h3>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginBottom: "0.6rem" }}>
        {severities.map((severity) => (
          <Button
            key={severity}
            variant="ghost"
            onClick={() => toggleSeverityFilter(severity)}
            className={severityFilters[severity] ? "button-primary" : ""}
          >
            {severity}
          </Button>
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginBottom: "0.8rem" }}>
        {categories.map((category) => (
          <Button
            key={category}
            variant="ghost"
            onClick={() => toggleCategoryFilter(category)}
            className={categoryFilters[category] ? "button-primary" : ""}
          >
            {category}
          </Button>
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
            <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
              <Badge variant={severityVariant(finding.severity)}>{finding.severity.toUpperCase()}</Badge>
              <strong>{finding.category}</strong>
            </div>
            <div style={{ marginTop: "0.25rem", overflowWrap: "anywhere", wordBreak: "break-word" }}>{finding.message}</div>
            <div
              style={{
                marginTop: "0.25rem",
                color: "var(--text-muted)",
                overflowWrap: "anywhere",
                wordBreak: "break-word",
                fontFamily: "var(--font-geist-mono)",
                fontSize: "0.82rem",
              }}
            >
              {finding.file_path}:{finding.line_start}
            </div>
            <div style={{ marginTop: "0.25rem", color: "var(--text-muted)" }}>
              Outcome: {findingOutcomes.find((item) => item.finding_index === index)?.outcome ?? "pending"}
            </div>
          </button>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <Button
              variant="ghost"
              onClick={() => onCopySuggestion(index)}
            >
              Copy suggestion
            </Button>
            <Button
              variant="danger"
              onClick={() => onDismiss(index)}
            >
              Dismiss
            </Button>
          </div>
        </article>
      ))}
    </section>
  );
}
