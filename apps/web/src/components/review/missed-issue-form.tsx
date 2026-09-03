"use client";

import { CATEGORIES, SEVERITIES, type Category, type Severity } from "@ai-code-review/shared-types";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { useCreateMissedIssue } from "@/hooks/use-missed-issues";
import { MISSED_ISSUE_HOW_FOUND, type MissedIssueHowFound } from "@/lib/api/quality";

interface MissedIssueFormProps {
  reviewId: number;
}

const inputStyle = {
  fontSize: "0.85rem",
  padding: "0.3rem 0.45rem",
  borderRadius: "0.35rem",
  border: "1px solid var(--border)",
  background: "var(--card)",
  color: "inherit",
} as const;

export function MissedIssueForm({ reviewId }: MissedIssueFormProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [filePath, setFilePath] = useState("");
  const [lineStart, setLineStart] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<Category>("correctness");
  const [severity, setSeverity] = useState<Severity>("medium");
  const [howFound, setHowFound] = useState<MissedIssueHowFound>("manual_report");
  const mutation = useCreateMissedIssue();

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const line = Number.parseInt(lineStart, 10);
    if (!filePath.trim() || !Number.isFinite(line) || line < 1 || !description.trim()) return;
    mutation.mutate(
      {
        review_id: reviewId,
        file_path: filePath.trim(),
        line_start: line,
        description: description.trim(),
        expected_category: category,
        expected_severity: severity,
        how_found: howFound,
      },
      {
        onSuccess: () => {
          setFilePath("");
          setLineStart("");
          setDescription("");
        },
      },
    );
  }

  return (
    <Panel aria-label="Report a missed issue">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "1rem", flexWrap: "wrap" }}>
        <div>
          <h3 style={{ margin: 0 }}>Missed something?</h3>
          <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)", fontSize: "0.9rem" }}>
            Record an issue the review should have flagged. It becomes a golden case for the eval harness.
          </p>
        </div>
        <Button variant="ghost" onClick={() => setIsOpen((value) => !value)} aria-expanded={isOpen}>
          {isOpen ? "Close" : "Report missed issue"}
        </Button>
      </div>
      {isOpen ? (
        <form onSubmit={handleSubmit} style={{ display: "grid", gap: "0.5rem", marginTop: "0.75rem", maxWidth: "40rem" }}>
          <label style={{ display: "grid", gap: "0.2rem", fontSize: "0.82rem" }}>
            File path
            <input value={filePath} onChange={(event) => setFilePath(event.target.value)} required style={inputStyle} placeholder="src/auth/token.py" />
          </label>
          <label style={{ display: "grid", gap: "0.2rem", fontSize: "0.82rem" }}>
            Line (at PR head)
            <input value={lineStart} onChange={(event) => setLineStart(event.target.value)} required inputMode="numeric" style={inputStyle} placeholder="42" />
          </label>
          <label style={{ display: "grid", gap: "0.2rem", fontSize: "0.82rem" }}>
            What was missed
            <textarea value={description} onChange={(event) => setDescription(event.target.value)} required maxLength={1000} rows={3} style={inputStyle} />
          </label>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <label style={{ display: "grid", gap: "0.2rem", fontSize: "0.82rem" }}>
              Category
              <select value={category} onChange={(event) => setCategory(event.target.value as Category)} style={inputStyle}>
                {CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ display: "grid", gap: "0.2rem", fontSize: "0.82rem" }}>
              Severity
              <select value={severity} onChange={(event) => setSeverity(event.target.value as Severity)} style={inputStyle}>
                {SEVERITIES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ display: "grid", gap: "0.2rem", fontSize: "0.82rem" }}>
              How found
              <select value={howFound} onChange={(event) => setHowFound(event.target.value as MissedIssueHowFound)} style={inputStyle}>
                {MISSED_ISSUE_HOW_FOUND.map((value) => (
                  <option key={value} value={value}>
                    {value.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Saving…" : "Save missed issue"}
            </Button>
            {mutation.isSuccess ? <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Recorded.</span> : null}
            {mutation.isError ? (
              <span style={{ fontSize: "0.8rem", color: "var(--severity-critical)" }}>
                {mutation.error instanceof Error ? mutation.error.message : "Unable to record missed issue."}
              </span>
            ) : null}
          </div>
        </form>
      ) : null}
    </Panel>
  );
}
