"use client";

import type { Finding } from "@ai-code-review/shared-types";

interface DiffViewerProps {
  findings: Finding[];
  selectedFindingIndex: number | null;
  onSelectFinding: (index: number) => void;
}

export function DiffViewer({ findings, selectedFindingIndex, onSelectFinding }: DiffViewerProps) {
  return (
    <section style={{ padding: "0.75rem", overflowY: "auto" }}>
      <h3 style={{ marginTop: 0 }}>Diff viewer</h3>
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        Placeholder unified view derived from findings until diff payload streaming is connected.
      </p>
      {findings.map((finding, index) => (
        <button
          key={`${finding.file_path}-${finding.line_start}-${index}`}
          type="button"
          onClick={() => onSelectFinding(index)}
          data-selected={selectedFindingIndex === index}
          style={{
            width: "100%",
            textAlign: "left",
            border: "1px solid var(--border)",
            borderRadius: "0.5rem",
            background: selectedFindingIndex === index ? "rgba(245, 158, 11, 0.2)" : "var(--card)",
            color: "inherit",
            padding: "0.6rem",
            marginBottom: "0.5rem",
          }}
        >
          <div style={{ color: "var(--text-muted)", fontFamily: "var(--font-geist-mono)" }}>
            {finding.file_path}:{finding.line_start}
          </div>
          <div style={{ marginTop: "0.3rem" }}>{finding.message}</div>
          {finding.suggestion ? (
            <pre
              style={{
                marginTop: "0.4rem",
                padding: "0.5rem",
                borderRadius: "0.375rem",
                background: "var(--background)",
                overflowX: "auto",
                border: "1px solid var(--border)",
              }}
            >
              {finding.suggestion}
            </pre>
          ) : null}
        </button>
      ))}
    </section>
  );
}
