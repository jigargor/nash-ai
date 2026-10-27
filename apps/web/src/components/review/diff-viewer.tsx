"use client";

import type { Finding } from "@ai-code-review/shared-types";

import { Badge } from "@/components/ui/badge";

interface DiffViewerProps {
  findings: Finding[];
  selectedFindingIndex: number | null;
  onSelectFinding: (index: number) => void;
}

const CODE_BLOCK_STYLE = {
  margin: "0.4rem 0 0",
  padding: "0.5rem",
  borderRadius: "0.375rem",
  background: "var(--background)",
  overflowX: "auto",
  border: "1px solid var(--border)",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  wordBreak: "break-word",
  fontFamily: "var(--font-geist-mono)",
  fontSize: "0.8rem",
} as const;

const LABEL_STYLE = { marginTop: "0.5rem", color: "var(--text-muted)", fontSize: "0.72rem" } as const;

function severityVariant(value: Finding["severity"]): "critical" | "high" | "medium" | "low" | "info" {
  if (value === "critical" || value === "high" || value === "medium" || value === "low") return value;
  return "info";
}

function hasText(value: string | null | undefined): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function DiffViewer({ findings, selectedFindingIndex, onSelectFinding }: DiffViewerProps) {
  return (
    <section style={{ padding: "0.75rem", overflowY: "auto" }}>
      <h3 style={{ marginTop: 0 }}>Diff viewer</h3>
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        Placeholder view built from finding anchors until the full diff payload is available.
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
            borderRadius: "var(--radius-md)",
            background: selectedFindingIndex === index ? "var(--accent-muted)" : "var(--card)",
            color: "inherit",
            padding: "0.6rem",
            marginBottom: "0.5rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", flexWrap: "wrap" }}>
            <Badge variant={severityVariant(finding.severity)}>{finding.severity.toUpperCase()}</Badge>
            <span
              style={{
                color: "var(--text-muted)",
                fontFamily: "var(--font-geist-mono)",
                overflowWrap: "anywhere",
                wordBreak: "break-word",
              }}
            >
              {finding.file_path}:{finding.line_start}
            </span>
          </div>
          <div style={{ marginTop: "0.3rem", overflowWrap: "anywhere", wordBreak: "break-word" }}>{finding.message}</div>
          {hasText(finding.patch_hunk) ? (
            <>
              <div style={LABEL_STYLE}>Hunk</div>
              <pre aria-label="Patch hunk" style={CODE_BLOCK_STYLE}>
                {finding.patch_hunk}
              </pre>
            </>
          ) : null}
          {hasText(finding.target_line_content) ? (
            <>
              <div style={LABEL_STYLE}>Target line</div>
              <pre aria-label="Target line content" style={CODE_BLOCK_STYLE}>
                {finding.target_line_content}
              </pre>
            </>
          ) : null}
          {hasText(finding.suggestion) ? (
            <>
              <div style={LABEL_STYLE}>Suggestion</div>
              <pre aria-label="Suggestion" style={CODE_BLOCK_STYLE}>
                {finding.suggestion}
              </pre>
            </>
          ) : null}
        </button>
      ))}
    </section>
  );
}
