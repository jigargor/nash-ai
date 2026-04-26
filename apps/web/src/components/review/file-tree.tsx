"use client";

import type { Finding } from "@ai-code-review/shared-types";

import { useReviewUiStore } from "@/stores/review-ui-store";

interface FileTreeProps {
  findings: Finding[];
  onSelectFinding: (index: number) => void;
}

export function FileTree({ findings, onSelectFinding }: FileTreeProps) {
  const expandedFiles = useReviewUiStore((state) => state.expandedFiles);
  const toggleFileExpanded = useReviewUiStore((state) => state.toggleFileExpanded);
  const selectedFindingIndex = useReviewUiStore((state) => state.selectedFindingIndex);

  const grouped = findings.reduce<Record<string, { finding: Finding; index: number }[]>>((acc, finding, index) => {
    acc[finding.file_path] = acc[finding.file_path] ?? [];
    acc[finding.file_path].push({ finding, index });
    return acc;
  }, {});

  return (
    <section style={{ borderRight: "1px solid var(--border)", padding: "0.75rem", overflowY: "auto" }}>
      <h3 style={{ marginTop: 0 }}>File tree</h3>
      {Object.entries(grouped).map(([filePath, items]) => {
        const isExpanded = expandedFiles[filePath] ?? true;
        return (
          <div key={filePath} style={{ marginBottom: "0.5rem" }}>
            <button
              type="button"
              onClick={() => toggleFileExpanded(filePath)}
              style={{ width: "100%", textAlign: "left", background: "transparent", border: "none", color: "inherit" }}
            >
              {isExpanded ? "▾" : "▸"} {filePath}
            </button>
            {isExpanded &&
              items.map(({ finding, index }) => (
                <button
                  key={`${filePath}-${index}`}
                  type="button"
                  onClick={() => onSelectFinding(index)}
                  data-selected={selectedFindingIndex === index}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    marginTop: "0.25rem",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--border)",
                    background: selectedFindingIndex === index ? "var(--accent-muted)" : "transparent",
                    color: "inherit",
                    padding: "0.3rem 0.5rem",
                  }}
                >
                  {finding.severity.toUpperCase()} · line {finding.line_start}
                </button>
              ))}
          </div>
        );
      })}
    </section>
  );
}
