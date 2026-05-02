"use client";

import { useEffect, useMemo, useState } from "react";

import type { ReviewModelAudit } from "@/lib/api/reviews";

// ---------------------------------------------------------------------------
// Stage metadata
// ---------------------------------------------------------------------------

const STAGE_META: Record<string, { label: string; icon: string; color: string }> = {
  fast_path: { label: "Fast-path scan", icon: "⚡", color: "#f59e0b" },
  primary: { label: "Primary review", icon: "🔍", color: "#60a5fa" },
  chunk_review: { label: "Chunk review", icon: "📦", color: "#818cf8" },
  synthesis: { label: "Synthesis", icon: "🔗", color: "#a78bfa" },
  challenger: { label: "Challenger", icon: "⚔", color: "#fb923c" },
  tie_break: { label: "Tie-break", icon: "⚖", color: "#f43f5e" },
  editor: { label: "Editor pass", icon: "✏", color: "#34d399" },
  final_post: { label: "Final filters", icon: "✅", color: "#4ade80" },
};

function stageMeta(stage: string) {
  return STAGE_META[stage] ?? { label: stage, icon: "◆", color: "var(--text-muted)" };
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function formatStageTimestamp(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
}

function parseUsd(value: string | null | undefined): number | null {
  if (!value) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return n;
}

function fmtUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `$${value.toFixed(6)}`;
}

function parseNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function estimateStageCostUsd(audit: ReviewModelAudit): number | null {
  const metadata = audit.metadata_json ?? {};
  const modelResolution =
    (metadata.model_resolution as Record<string, unknown> | undefined) ?? {};
  const pricing = (modelResolution.pricing as Record<string, unknown> | undefined) ?? {};
  const llmUsage = (metadata.llm_usage as Record<string, unknown> | undefined) ?? {};

  const inputPer1M = parseNumber(pricing.input_per_1m_usd);
  const outputPer1M = parseNumber(pricing.output_per_1m_usd);
  if (inputPer1M == null || outputPer1M == null) return null;

  const cachedPer1M = parseNumber(pricing.cached_input_per_1m_usd) ?? inputPer1M;
  const cachedInputTokens = Math.max(
    0,
    parseNumber(llmUsage.cached_input_tokens_seen) ?? 0,
  );
  const effectiveInputTokens = Math.max(0, audit.input_tokens - cachedInputTokens);

  return (
    (effectiveInputTokens * inputPer1M +
      cachedInputTokens * cachedPer1M +
      audit.output_tokens * outputPer1M) /
    1_000_000
  );
}

function formatElapsedMs(ms: number | null): string {
  if (ms == null || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  if (hours > 0) return `${hours} h ${minutes % 60} m ${seconds % 60} s`;
  if (minutes > 0) return `${minutes} m ${seconds % 60} s`;
  return `${seconds} s`;
}

function deriveLivePipelinePresentation(
  hasChunking: boolean,
  audits: ReviewModelAudit[],
): { label: string; icon: string; color: string } {
  if (audits.length === 0) {
    return { label: "Starting pipeline…", icon: "⏳", color: "var(--text-muted)" };
  }
  const last = audits[audits.length - 1].stage;
  if (!hasChunking && (last === "chunk_review" || last === "synthesis")) return stageMeta(last);
  return stageMeta(last);
}

function extractStatusCode(audit: ReviewModelAudit): number | null {
  const reason = (audit.metadata_json?.reason ?? audit.metadata_json?.fallback_reason) as
    | string
    | undefined;
  if (!reason) return null;
  const patterns = [/error code:\s*(\d{3})/i, /status(?:_code| code)?[:=]\s*(\d{3})/i];
  for (const pattern of patterns) {
    const match = reason.match(pattern);
    if (match) return Number(match[1]);
  }
  return null;
}

function isFailedStage(audit: ReviewModelAudit): boolean {
  const code = extractStatusCode(audit);
  if (code != null && code >= 400) return true;
  const reason = (audit.metadata_json?.reason as string | undefined)?.toLowerCase() ?? "";
  // Rationale text often mentions "error handling" on successful fast-path scans; do not treat "error" as failure.
  return reason.includes("failed");
}

function CopyDebugJsonButton({ getPayload }: { getPayload: () => Record<string, unknown> }) {
  const [copied, setCopied] = useState(false);
  async function handleClick(): Promise<void> {
    try {
      await navigator.clipboard.writeText(JSON.stringify(getPayload(), null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }
  return (
    <button
      type="button"
      onClick={() => void handleClick()}
      title={copied ? "Copied" : "Copy debug JSON (action chain, artifacts, findings)"}
      aria-label={copied ? "Copied JSON to clipboard" : "Copy debug JSON to clipboard"}
      style={{
        flexShrink: 0,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "2.25rem",
        height: "2.25rem",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border-strong)",
        background: copied ? "var(--accent-muted)" : "var(--card-muted)",
        color: "var(--text-muted)",
        cursor: "pointer",
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </svg>
    </button>
  );
}

function getRaw(meta: Record<string, unknown> | null, key: string): unknown {
  return meta?.[key] ?? undefined;
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

// ---------------------------------------------------------------------------
// Decision badge
// ---------------------------------------------------------------------------

function DecisionBadge({ decision }: { decision: string | null }) {
  if (!decision) return null;
  const colorMap: Record<string, string> = {
    generated: "#34d399",
    posted: "#4ade80",
    edited: "#a78bfa",
    skipped: "#94a3b8",
    challenged: "#fb923c",
    tie_break: "#f43f5e",
    skip_review: "#6b7280",
    light_review: "#f59e0b",
    full_review: "#60a5fa",
  };
  const color = colorMap[decision] ?? "#6b7280";
  return (
    <span
      style={{
        fontSize: "0.7rem",
        fontWeight: 500,
        color,
        border: `1px solid ${color}44`,
        borderRadius: "4px",
        padding: "0.1rem 0.4rem",
        whiteSpace: "nowrap",
      }}
    >
      {decision}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Stage body — stage-specific detail panels
// ---------------------------------------------------------------------------

function FastPathBody({ meta }: { meta: Record<string, unknown> | null }) {
  const decision = String(getRaw(meta, "decision") ?? "");
  const confidence = getRaw(meta, "confidence") as number | undefined;
  const riskLabels = toStringArray(getRaw(meta, "risk_labels"));
  const reason = getRaw(meta, "reason") as string | undefined;
  const fileClasses = (getRaw(meta, "file_classes") as Record<string, number> | undefined) ?? {};
  const reviewSurfacePaths = toStringArray(
    getRaw(meta, "review_surface_paths") ?? getRaw(meta, "review_surface"),
  );
  const reviewSurfaceCountRaw = getRaw(meta, "review_surface_count");
  const reviewSurfaceCount =
    typeof reviewSurfaceCountRaw === "number" && Number.isFinite(reviewSurfaceCountRaw)
      ? reviewSurfaceCountRaw
      : reviewSurfacePaths.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
      {reason ? (
        <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--text-muted)", overflowWrap: "anywhere", wordBreak: "break-word" }}>
          {reason}
        </p>
      ) : null}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem", alignItems: "center" }}>
        {confidence != null && (
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            confidence: <strong style={{ color: "var(--text-primary)" }}>{confidence}%</strong>
          </span>
        )}
        {reviewSurfaceCount > 0 && (
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            · files reviewed:{" "}
            <strong style={{ color: "var(--text-primary)" }}>{reviewSurfaceCount}</strong>
          </span>
        )}
      </div>
      {reviewSurfacePaths.length > 0 && (
        <details>
          <summary style={{ cursor: "pointer", fontSize: "0.72rem", color: "var(--text-muted)" }}>
            reviewed paths
          </summary>
          <div style={{ marginTop: "0.35rem", display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
            {reviewSurfacePaths.map((path) => (
              <span
                key={path}
                style={{
                  fontSize: "0.7rem",
                  background: "var(--card-muted)",
                  border: "1px solid var(--border-strong)",
                  borderRadius: "4px",
                  padding: "0.1rem 0.4rem",
                  color: "var(--text-muted)",
                }}
              >
                {path}
              </span>
            ))}
          </div>
        </details>
      )}
      {riskLabels.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
          {riskLabels.map((label) => (
            <span
              key={label}
              style={{
                fontSize: "0.7rem",
                background: "rgba(245,158,11,0.1)",
                border: "1px solid rgba(245,158,11,0.3)",
                color: "#f59e0b",
                borderRadius: "4px",
                padding: "0.1rem 0.4rem",
              }}
            >
              {label}
            </span>
          ))}
        </div>
      )}
      {Object.keys(fileClasses).length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
          {Object.entries(fileClasses).map(([cls, count]) => (
            <span key={cls} style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
              {cls}: <strong style={{ color: "var(--text-primary)" }}>{count}</strong>
            </span>
          ))}
        </div>
      )}
      {decision === "skip_review" && (
        <p style={{ margin: 0, fontSize: "0.8rem", color: "#f59e0b", fontWeight: 500 }}>
          ↳ Full review skipped — low risk score
        </p>
      )}
    </div>
  );
}

function ContextBudgetHelpIcon() {
  return (
    <span
      title="Segments removed to stay under the configured prompt token budget. Later stages (editor, filters) still run, but the model may have missed context tied to dropped hunks or files—increase chunking budgets or narrow the diff if reviews feel shallow."
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "1.1rem",
        height: "1.1rem",
        borderRadius: "999px",
        border: "1px solid #fb923c66",
        color: "#fb923c",
        fontSize: "0.65rem",
        fontWeight: 700,
        cursor: "help",
        flexShrink: 0,
      }}
      aria-label="Why dropped context matters"
    >
      ?
    </span>
  );
}

function PrimaryBody({ meta }: { meta: Record<string, unknown> | null }) {
  const [summaryOpen, setSummaryOpen] = useState(false);
  const sysTokens = getRaw(meta, "system_prompt_tokens") as number | undefined;
  const userTokens = getRaw(meta, "user_prompt_tokens") as number | undefined;
  const excerpt = getRaw(meta, "output_summary_excerpt") as string | undefined;
  const fullSummary = getRaw(meta, "output_summary_full") as string | undefined;
  const contextLayers = getRaw(meta, "context_layers") as Record<string, unknown> | undefined;
  const layerUsage = contextLayers?.layer_token_usage as Record<string, number> | undefined;
  const dropped = contextLayers?.dropped_segments as string[] | undefined;
  const baseSummary = excerpt ?? fullSummary ?? "";
  const displaySummary =
    summaryOpen && fullSummary && excerpt && fullSummary.length > excerpt.length ? fullSummary : baseSummary;
  const canExpand = Boolean(fullSummary && excerpt && fullSummary.length > excerpt.length);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
      {(sysTokens != null || userTokens != null) && (
        <div style={{ display: "flex", gap: "1rem" }}>
          {sysTokens != null && (
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              system prompt: <strong style={{ color: "var(--text-primary)" }}>{fmtTokens(sysTokens)} tokens</strong>
            </span>
          )}
          {userTokens != null && (
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              user prompt: <strong style={{ color: "var(--text-primary)" }}>{fmtTokens(userTokens)} tokens</strong>
            </span>
          )}
        </div>
      )}
      {layerUsage && Object.keys(layerUsage).length > 0 && (
        <div>
          <p style={{ margin: "0 0 0.3rem", fontSize: "0.7rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Context layers
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {Object.entries(layerUsage).map(([layer, tokens]) => (
              <span key={layer} style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
                {layer}: <strong style={{ color: "var(--text-primary)" }}>{fmtTokens(tokens)}</strong>
              </span>
            ))}
          </div>
        </div>
      )}
      {dropped && dropped.length > 0 && (
        <p style={{ margin: 0, fontSize: "0.75rem", color: "#fb923c", display: "flex", alignItems: "center", gap: "0.35rem" }}>
          <span>
            ⚠ {dropped.length} context segment{dropped.length !== 1 ? "s" : ""} dropped (token budget)
          </span>
          <ContextBudgetHelpIcon />
        </p>
      )}
      {displaySummary && (
        <div>
          <blockquote
            style={{
              margin: 0,
              borderLeft: "2px solid var(--border-strong)",
              paddingLeft: "0.75rem",
              fontSize: "0.78rem",
              color: "var(--text-muted)",
              fontStyle: "italic",
              whiteSpace: "pre-wrap",
              overflowWrap: "anywhere",
              wordBreak: "break-word",
            }}
          >
            {displaySummary}
          </blockquote>
          {canExpand ? (
            <button
              type="button"
              onClick={() => setSummaryOpen((o) => !o)}
              style={{
                marginTop: "0.35rem",
                background: "none",
                border: "none",
                color: "var(--accent)",
                fontSize: "0.72rem",
                cursor: "pointer",
                padding: 0,
              }}
            >
              {summaryOpen ? "Show shorter excerpt" : "Show full primary summary"}
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

function ChunkBody({ meta }: { meta: Record<string, unknown> | null }) {
  const [filesOpen, setFilesOpen] = useState(false);
  const chunkId = getRaw(meta, "chunk_id") as string | undefined;
  const fileCount = getRaw(meta, "chunk_file_count") as number | undefined;
  const filePaths = (getRaw(meta, "chunk_file_paths") as string[] | undefined) ?? [];
  const estTokens = getRaw(meta, "chunk_estimated_tokens") as number | undefined;
  const excerpt = getRaw(meta, "output_summary_excerpt") as string | undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      {chunkId && <p style={{ margin: 0, fontSize: "0.7rem", color: "var(--text-muted)", fontFamily: "monospace" }}>chunk: {chunkId}</p>}
      <div style={{ display: "flex", gap: "1rem" }}>
        {fileCount != null && (
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            files: <strong style={{ color: "var(--text-primary)" }}>{fileCount}</strong>
          </span>
        )}
        {estTokens != null && (
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            est. tokens: <strong style={{ color: "var(--text-primary)" }}>{fmtTokens(estTokens)}</strong>
          </span>
        )}
      </div>
      {filePaths.length > 0 && (
        <div>
          <button
            onClick={() => setFilesOpen((o) => !o)}
            style={{ background: "none", border: "none", color: "var(--text-muted)", fontSize: "0.72rem", cursor: "pointer", padding: 0, display: "flex", alignItems: "center", gap: "0.3rem" }}
          >
            <span style={{ display: "inline-block", transition: "transform 0.1s", transform: filesOpen ? "rotate(90deg)" : "none" }}>▶</span>
            {filesOpen ? "Hide" : "Show"} files ({filePaths.length})
          </button>
          {filesOpen && (
            <div style={{ marginTop: "0.3rem", display: "flex", flexDirection: "column", gap: "0.15rem" }}>
              {filePaths.map((p) => (
                <span key={p} style={{ fontFamily: "monospace", fontSize: "0.72rem", color: "var(--text-muted)" }}>{p}</span>
              ))}
            </div>
          )}
        </div>
      )}
      {excerpt && (
        <blockquote style={{ margin: 0, borderLeft: "2px solid var(--border-strong)", paddingLeft: "0.6rem", fontSize: "0.75rem", color: "var(--text-muted)", fontStyle: "italic" }}>
          {excerpt}
        </blockquote>
      )}
    </div>
  );
}

function ChallengerBody({ audit }: { audit: ReviewModelAudit }) {
  const meta = audit.metadata_json;
  const primaryCount = getRaw(meta, "primary_findings_count") as number | undefined;
  const challengerCount = getRaw(meta, "challenger_findings_count") as number | undefined;
  const conflictScore = audit.conflict_score;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
      {(primaryCount != null || challengerCount != null) && (
        <div style={{ display: "flex", gap: "1.5rem" }}>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            primary findings: <strong style={{ color: "var(--text-primary)" }}>{primaryCount ?? "–"}</strong>
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            challenger findings: <strong style={{ color: "var(--text-primary)" }}>{challengerCount ?? "–"}</strong>
          </span>
        </div>
      )}
      {conflictScore != null && (
        <div>
          <p style={{ margin: "0 0 0.3rem", fontSize: "0.7rem", color: "var(--text-muted)" }}>
            conflict score: <strong style={{ color: conflictScore >= 50 ? "#f43f5e" : conflictScore >= 25 ? "#fb923c" : "#34d399" }}>{conflictScore}%</strong>
          </p>
          <div style={{ height: "4px", borderRadius: "2px", background: "var(--border-strong)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${conflictScore}%`, background: conflictScore >= 50 ? "#f43f5e" : conflictScore >= 25 ? "#fb923c" : "#34d399", borderRadius: "2px", transition: "width 0.3s" }} />
          </div>
        </div>
      )}
    </div>
  );
}

function EditorBody({ audit, debugArtifacts }: { audit: ReviewModelAudit; debugArtifacts: Record<string, unknown> | null }) {
  const meta = audit.metadata_json;
  const stageReason = getRaw(meta, "reason") as string | undefined;
  const keepCount = getRaw(meta, "keep_count") as number | undefined;
  const dropCount = getRaw(meta, "drop_count") as number | undefined;
  const modifyCount = getRaw(meta, "modify_count") as number | undefined;
  const editorActions = debugArtifacts?.editor_actions as Record<string, number> | undefined;
  const dropReasons = debugArtifacts?.editor_drop_reasons as Record<string, number> | undefined;

  const keep = keepCount ?? editorActions?.keep ?? 0;
  const drop = dropCount ?? editorActions?.drop ?? 0;
  const modify = modifyCount ?? editorActions?.modify ?? 0;
  const total = keep + drop + modify;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
      {total > 0 && (
        <div style={{ display: "flex", gap: "1.5rem" }}>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>keep: <strong style={{ color: "#34d399" }}>{keep}</strong></span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>modify: <strong style={{ color: "#a78bfa" }}>{modify}</strong></span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>drop: <strong style={{ color: "#f43f5e" }}>{drop}</strong></span>
        </div>
      )}
      {dropReasons && Object.keys(dropReasons).length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
          {Object.entries(dropReasons).map(([reason, count]) => (
            <span key={reason} style={{ fontSize: "0.7rem", background: "rgba(244,63,94,0.08)", border: "1px solid rgba(244,63,94,0.2)", color: "#f43f5e", borderRadius: "4px", padding: "0.1rem 0.4rem" }}>
              {reason}: {count}
            </span>
          ))}
        </div>
      )}
      {total === 0 && (!dropReasons || Object.keys(dropReasons).length === 0) && (
        <p style={{ margin: 0, fontSize: "0.75rem", color: "var(--text-muted)" }}>
          {audit.decision === "skipped" || stageReason === "no_findings_to_edit"
            ? "Editor pass skipped — no findings from primary."
            : "No edit decisions (nothing to refine)."}
        </p>
      )}
    </div>
  );
}

function FinalPostBody({ debugArtifacts }: { debugArtifacts: Record<string, unknown> | null }) {
  const validatorDropped = (debugArtifacts?.validator_dropped as unknown[] | undefined) ?? [];
  const confidenceThreshold = debugArtifacts?.confidence_threshold as number | undefined;
  const retryTriggered = debugArtifacts?.retry_triggered as boolean | undefined;
  const retryRecovered = debugArtifacts?.retry_recovered as number | undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      {confidenceThreshold != null && (
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          confidence threshold applied: <strong style={{ color: "var(--text-primary)" }}>{confidenceThreshold}%</strong>
        </span>
      )}
      {validatorDropped.length > 0 && (
        <span style={{ fontSize: "0.75rem", color: "#fb923c" }}>
          validator dropped: <strong>{validatorDropped.length}</strong> finding{validatorDropped.length !== 1 ? "s" : ""}
        </span>
      )}
      {retryTriggered && (
        <span style={{ fontSize: "0.75rem", color: "#f59e0b" }}>
          ↺ retry triggered{retryRecovered != null ? ` · ${retryRecovered} findings recovered` : ""}
        </span>
      )}
    </div>
  );
}

function LiveStageProgress({ label, icon }: { label: string; icon: string }) {
  return (
    <div
      style={{
        marginBottom: "0.75rem",
        border: "2px dashed var(--border-strong)",
        borderRadius: "var(--radius-md)",
        padding: "1.1rem 1rem",
        minHeight: "8.5rem",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "0.45rem",
        background: "var(--card-muted)",
        textAlign: "center",
      }}
    >
      <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600 }}>
        Current pipeline step
      </p>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "0.55rem", flexWrap: "wrap", width: "100%" }}>
        <span style={{ fontSize: "1.35rem", lineHeight: 1 }} aria-hidden>
          {icon}
        </span>
        <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "var(--text-primary)" }}>{label}</span>
      </div>
      <div className="orbit-loader" aria-hidden>
        <span className="orbit-dot orbit-dot-1" />
        <span className="orbit-dot orbit-dot-2" />
        <span className="orbit-dot orbit-dot-3" />
      </div>
      <p style={{ margin: 0, fontSize: "0.7rem", color: "var(--text-muted)", maxWidth: "28rem", lineHeight: 1.45 }}>
        Waiting for this step to finish. Completed step details appear in this same panel.
      </p>
      <style jsx>{`
        .orbit-loader {
          position: relative;
          width: 1.5rem;
          height: 1.5rem;
          animation: orbit-spin 1.4s linear infinite;
        }
        .orbit-dot {
          position: absolute;
          width: 0.32rem;
          height: 0.32rem;
          border-radius: 999px;
          background: var(--accent);
          top: 50%;
          left: 50%;
          margin-top: -0.16rem;
          margin-left: -0.16rem;
        }
        .orbit-dot-1 {
          transform: translateY(-0.65rem);
        }
        .orbit-dot-2 {
          transform: rotate(120deg) translateY(-0.65rem);
        }
        .orbit-dot-3 {
          transform: rotate(240deg) translateY(-0.65rem);
        }
        @keyframes orbit-spin {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single stage card
// ---------------------------------------------------------------------------

function StageCard({
  audit,
  debugArtifacts,
  defaultOpen,
  isLast,
  estimatedCostUsd,
}: {
  audit: ReviewModelAudit;
  debugArtifacts: Record<string, unknown> | null;
  defaultOpen: boolean;
  isLast: boolean;
  estimatedCostUsd: number | null;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const { label, icon, color } = stageMeta(audit.stage);
  const startedAtLabel = formatStageTimestamp(audit.created_at);
  const statusCode = extractStatusCode(audit) ?? 200;
  const statusFailed = isFailedStage(audit);
  const meta = audit.stage === "final_post" ? null : audit.metadata_json;

  function renderBody() {
    switch (audit.stage) {
      case "fast_path": return <FastPathBody meta={audit.metadata_json} />;
      case "primary": return <PrimaryBody meta={audit.metadata_json} />;
      case "chunk_review": return <ChunkBody meta={audit.metadata_json} />;
      case "challenger": return <ChallengerBody audit={audit} />;
      case "tie_break": return null;
      case "editor": return <EditorBody audit={audit} debugArtifacts={debugArtifacts} />;
      case "final_post": return <FinalPostBody debugArtifacts={debugArtifacts} />;
      default: return null;
    }
    void meta; // suppress unused var
  }

  const body = renderBody();
  const hasBody = body !== null;

  return (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      {/* Timeline line */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0, width: "24px" }}>
        <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: `${color}22`, border: `2px solid ${color}66`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.8rem", flexShrink: 0 }}>
          {icon}
        </div>
        {!isLast && (
          <div style={{ width: "1px", flex: 1, minHeight: "16px", borderLeft: "1px dashed var(--border-strong)", marginTop: "4px" }} />
        )}
      </div>

      {/* Card */}
      <div style={{ flex: 1, marginBottom: isLast ? 0 : "0.5rem" }}>
        <button
          onClick={() => hasBody && setOpen((o) => !o)}
          style={{
            width: "100%",
            textAlign: "left",
            background: open ? `${color}0a` : "transparent",
            border: `1px solid ${open ? color + "33" : "var(--border)"}`,
            borderRadius: "var(--radius-md)",
            padding: "0.5rem 0.75rem",
            cursor: hasBody ? "pointer" : "default",
            color: "inherit",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem", alignItems: "stretch", width: "100%" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem", width: "100%" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap", minWidth: 0 }}>
                <span style={{ fontWeight: 600, fontSize: "0.85rem", color: "var(--text-primary)" }}>{label}</span>
                <DecisionBadge decision={audit.decision} />
                {hasBody ? (
                  <span
                    style={{
                      fontSize: "0.65rem",
                      color: "var(--text-muted)",
                      display: "inline-block",
                      transform: open ? "rotate(90deg)" : "none",
                      transition: "transform 0.15s",
                    }}
                  >
                    ▶
                  </span>
                ) : null}
                <span
                  style={{
                    fontSize: "0.68rem",
                    fontWeight: 600,
                    color: statusFailed ? "#f43f5e" : "#34d399",
                  }}
                  title={statusFailed ? "Detected stage failure" : "Successful stage response"}
                >
                  {statusCode}
                </span>
              </div>
              {startedAtLabel ? (
                <span
                  style={{
                    fontSize: "0.68rem",
                    color: "var(--text-muted)",
                    marginLeft: "auto",
                    flexShrink: 0,
                    fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
                  }}
                  title="Stage started"
                >
                  {startedAtLabel}
                </span>
              ) : null}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", alignItems: "center", width: "100%" }}>
              <span
                style={{
                  fontSize: "0.7rem",
                  background: "var(--card-muted)",
                  border: "1px solid var(--border-strong)",
                  borderRadius: "999px",
                  padding: "0.05rem 0.5rem",
                  color: "var(--text-muted)",
                  fontFamily: "monospace",
                  overflowWrap: "anywhere",
                  wordBreak: "break-word",
                  maxWidth: "100%",
                }}
              >
                {audit.provider}/{audit.model}
              </span>
              {audit.stage_duration_ms != null ? (
                <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>{fmtMs(audit.stage_duration_ms)}</span>
              ) : null}
              <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                {fmtTokens(audit.total_tokens)} tok
              </span>
              {audit.findings_count != null ? (
                <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                  {audit.stage === "fast_path" || audit.metadata_json?.produces_findings === false
                    ? "findings: N/A"
                    : `${audit.findings_count} finding${audit.findings_count !== 1 ? "s" : ""}${
                        audit.accepted_findings_count != null &&
                        audit.accepted_findings_count !== audit.findings_count
                          ? ` → ${audit.accepted_findings_count} kept`
                          : ""
                      }`}
                </span>
              ) : null}
              {estimatedCostUsd != null ? (
                <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                  · est. {fmtUsd(estimatedCostUsd)}
                </span>
              ) : null}
            </div>
          </div>
        </button>
        {open && hasBody && (
          <div style={{ marginTop: "0.4rem", paddingLeft: "0.75rem", paddingRight: "0.75rem", paddingBottom: "0.5rem" }}>
            {body}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chunking callout
// ---------------------------------------------------------------------------

interface SkippedFileDetail {
  path: string;
  file_class?: string;
  reason?: string;
}

function SkippedFilesHelpIcon() {
  return (
    <span
      title="These paths were not part of the chunked primary review surface (often generated, lockfile, or docs-only). Risk: regressions there rely on other checks or human review—expand include_file_classes in .codereview.yml if they should be reviewed."
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "1.1rem",
        height: "1.1rem",
        borderRadius: "999px",
        border: "1px solid var(--border-strong)",
        color: "var(--text-muted)",
        fontSize: "0.65rem",
        fontWeight: 700,
        cursor: "help",
        flexShrink: 0,
      }}
      aria-label="Why skipped files matter"
    >
      ?
    </span>
  );
}

function ChunkingCallout({ plan }: { plan: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const [skippedOpen, setSkippedOpen] = useState(false);
  const chunks = (plan.chunks as string[] | undefined) ?? [];
  const skipped = (plan.skipped_files as string[] | undefined) ?? [];
  const skippedDetails = (plan.skipped_file_details as SkippedFileDetail[] | undefined) ?? [];
  const isPartial = plan.is_partial as boolean | undefined;
  const coverageNote = plan.coverage_note as string | undefined;
  const skippedRows: SkippedFileDetail[] =
    skippedDetails.length > 0
      ? skippedDetails
      : skipped.map((path) => ({ path, reason: "Excluded by chunking pre-pass (no detailed reason stored)." }));

  return (
    <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.5rem" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0, width: "24px" }}>
        <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: "rgba(129,140,248,0.12)", border: "1px dashed #818cf8", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.8rem" }}>📋</div>
        <div style={{ width: "1px", flex: 1, minHeight: "16px", borderLeft: "1px dashed var(--border-strong)", marginTop: "4px" }} />
      </div>
      <div style={{ flex: 1 }}>
        <button
          onClick={() => setOpen((o) => !o)}
          style={{ width: "100%", textAlign: "left", background: "rgba(129,140,248,0.05)", border: "1px dashed #818cf844", borderRadius: "var(--radius-md)", padding: "0.4rem 0.75rem", cursor: "pointer", color: "inherit" }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
            <span style={{ fontWeight: 600, fontSize: "0.82rem", color: "#818cf8" }}>Chunked into {chunks.length} group{chunks.length !== 1 ? "s" : ""}</span>
            {isPartial && <span style={{ fontSize: "0.7rem", color: "#fb923c", border: "1px solid #fb923c44", borderRadius: "4px", padding: "0.05rem 0.35rem" }}>partial</span>}
            {skipped.length > 0 && (
              <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
                {skipped.length} file{skipped.length !== 1 ? "s" : ""} skipped
                <SkippedFilesHelpIcon />
              </span>
            )}
            {coverageNote && <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginLeft: "auto" }}>{coverageNote}</span>}
            <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", display: "inline-block", transform: open ? "rotate(90deg)" : "none", transition: "transform 0.15s" }}>▶</span>
          </div>
        </button>
        {open && (
          <div style={{ marginTop: "0.35rem", paddingLeft: "0.75rem", display: "flex", flexDirection: "column", gap: "0.2rem" }}>
            {chunks.map((id, i) => (
              <span key={id} style={{ fontSize: "0.72rem", fontFamily: "monospace", color: "var(--text-muted)" }}>
                chunk {i + 1}: {id}
              </span>
            ))}
            {skipped.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <button
                  type="button"
                  onClick={() => setSkippedOpen((s) => !s)}
                  style={{
                    alignSelf: "flex-start",
                    background: "none",
                    border: "none",
                    color: "#fb923c",
                    fontSize: "0.72rem",
                    cursor: "pointer",
                    padding: 0,
                    display: "flex",
                    alignItems: "center",
                    gap: "0.3rem",
                  }}
                >
                  <span style={{ display: "inline-block", transform: skippedOpen ? "rotate(90deg)" : "none", transition: "transform 0.1s" }}>▶</span>
                  ⚠ {skipped.length} file{skipped.length !== 1 ? "s" : ""} not reviewed
                </button>
                {skippedOpen && (
                  <ul style={{ margin: "0.15rem 0 0", paddingLeft: "1.1rem", fontSize: "0.72rem", color: "var(--text-muted)" }}>
                    {skippedRows.map((row) => (
                      <li key={row.path} style={{ marginBottom: "0.25rem" }}>
                        <code style={{ fontSize: "0.7rem" }}>{row.path}</code>
                        {row.file_class ? (
                          <span style={{ marginLeft: "0.35rem" }}>
                            · class <strong>{row.file_class}</strong>
                          </span>
                        ) : null}
                        {row.reason ? <div style={{ marginTop: "0.1rem", fontStyle: "italic" }}>{row.reason}</div> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Token summary footer
// ---------------------------------------------------------------------------

function BottomPanelSummary({
  audits,
  stageEstimatedCostUsd,
  postedFindingsCount,
  pipelineStagedFindingsPeak,
  isInFlight,
  nowMs,
}: {
  audits: ReviewModelAudit[];
  stageEstimatedCostUsd: number | null;
  postedFindingsCount: number;
  pipelineStagedFindingsPeak: number;
  isInFlight: boolean;
  nowMs: number;
}) {
  let totalInput = 0,
    totalOutput = 0,
    totalAll = 0;
  for (const a of audits) {
    totalInput += a.input_tokens;
    totalOutput += a.output_tokens;
    totalAll += a.total_tokens;
  }

  const showTokens = totalAll > 0;
  const showCost = stageEstimatedCostUsd != null;
  const startedAtMs =
    audits.length > 0 && audits[0].created_at ? new Date(audits[0].created_at).getTime() : null;
  const endedAtMs =
    !isInFlight && audits.length > 0 && audits[audits.length - 1].created_at
      ? new Date(audits[audits.length - 1].created_at!).getTime()
      : null;
  const runtimeMs =
    startedAtMs == null
      ? null
      : endedAtMs == null
        ? isInFlight
          ? nowMs - startedAtMs
          : null
        : endedAtMs - startedAtMs;
  const completedNodes = audits.length;

  return (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <div style={{ width: "24px", flexShrink: 0 }} />
      <div style={{ flex: 1, borderTop: "1px solid var(--border)", paddingTop: "0.6rem", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.55rem 0.75rem" }}>
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          Start: <strong style={{ color: "var(--text-primary)" }}>{formatStageTimestamp(audits[0]?.created_at ?? null) ?? "—"}</strong>
        </span>
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          End:{" "}
          <strong style={{ color: "var(--text-primary)" }}>
            {isInFlight ? "In progress…" : formatStageTimestamp(audits[audits.length - 1]?.created_at ?? null) ?? "—"}
          </strong>
        </span>
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          Runtime: <strong style={{ color: "var(--text-primary)" }}>{formatElapsedMs(runtimeMs)}</strong>
          {runtimeMs != null && isInFlight ? " so far" : ""}
        </span>
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          Nodes: <strong style={{ color: "var(--text-primary)" }}>{completedNodes}</strong>
        </span>
        {showTokens ? (
          <>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Total: <strong style={{ color: "var(--text-primary)" }}>{fmtTokens(totalAll)}</strong>
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Input: <strong style={{ color: "var(--text-primary)" }}>{fmtTokens(totalInput)}</strong>
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Output: <strong style={{ color: "var(--text-primary)" }}>{fmtTokens(totalOutput)}</strong>
            </span>
          </>
        ) : null}
        {showCost ? (
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            Est. cost: <strong style={{ color: "var(--accent)" }}>{fmtUsd(stageEstimatedCostUsd)}</strong>
          </span>
        ) : null}
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          Posted: <strong style={{ color: "var(--text-primary)" }}>{postedFindingsCount}</strong>
          {pipelineStagedFindingsPeak > postedFindingsCount ? (
            <>
              {" "}
              · pipeline max:{" "}
              <strong style={{ color: "var(--text-primary)" }}>{pipelineStagedFindingsPeak}</strong>
            </>
          ) : null}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ReviewPipeline component
// ---------------------------------------------------------------------------

interface ReviewPipelineProps {
  audits: ReviewModelAudit[];
  debugArtifacts: Record<string, unknown> | null;
  costUsd?: string | null;
  isInFlight?: boolean;
  /** Final posted findings count (matches PR review summary). */
  postedFindingsCount: number;
  /** Largest `findings_count` from any pipeline stage (may exceed posted when a later stage failed). */
  pipelineStagedFindingsPeak: number;
  /** Shown when there are no model-audit rows (e.g. still running or audits not persisted). */
  pipelineEmptyHint?: string | null;
  /** When set, header shows a copy control for JSON export. */
  getDebugExportPayload?: () => Record<string, unknown>;
}

const AUTO_OPEN_STAGES = new Set(["primary", "challenger", "tie_break"]);
const STAGE_SEQUENCE = ["fast_path", "primary", "chunk_review", "synthesis", "challenger", "tie_break", "editor", "final_post"];

function nextStageLabel(currentStage: string | null, hasChunking: boolean): { label: string; icon: string } {
  if (!currentStage) return { label: "Starting pipeline…", icon: "⏳" };
  const currentIndex = STAGE_SEQUENCE.indexOf(currentStage);
  const next = STAGE_SEQUENCE[currentIndex + 1];
  if (!next) return { label: "Finalizing review", icon: "✅" };
  if (!hasChunking && (next === "chunk_review" || next === "synthesis")) {
    return nextStageLabel(next, hasChunking);
  }
  const meta = stageMeta(next);
  return { label: meta.label, icon: meta.icon };
}

export function ReviewPipeline({
  audits,
  debugArtifacts,
  costUsd,
  isInFlight,
  postedFindingsCount,
  pipelineStagedFindingsPeak,
  pipelineEmptyHint,
  getDebugExportPayload,
}: ReviewPipelineProps) {
  const chunkingPlan = debugArtifacts?.chunking_plan as Record<string, unknown> | undefined;
  const hasChunking = chunkingPlan && Array.isArray(chunkingPlan.chunks) && (chunkingPlan.chunks as unknown[]).length > 1;
  const [nowMs, setNowMs] = useState(() => Date.now());
  const latestAudit = audits[audits.length - 1] ?? null;
  const pendingMeta = nextStageLabel(latestAudit?.stage ?? null, Boolean(hasChunking));
  const stageCostByAuditId = useMemo(() => {
    const entries = new Map<number, number | null>();
    for (const audit of audits) entries.set(audit.id, estimateStageCostUsd(audit));
    return entries;
  }, [audits]);
  const stageEstimatedCostUsd = useMemo(() => {
    let total = 0;
    let hasCost = false;
    for (const value of stageCostByAuditId.values()) {
      if (value == null) continue;
      hasCost = true;
      total += value;
    }
    return hasCost ? total : parseUsd(costUsd ?? null);
  }, [costUsd, stageCostByAuditId]);

  useEffect(() => {
    if (!isInFlight) return;
    const interval = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [isInFlight]);

  return (
    <div
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        padding: "1rem",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "0.75rem",
          marginBottom: "0.65rem",
        }}
      >
        <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>
          Review pipeline
        </p>
        {getDebugExportPayload ? <CopyDebugJsonButton getPayload={getDebugExportPayload} /> : null}
      </div>
      <p style={{ margin: "0 0 0.65rem", fontSize: "0.78rem", color: "var(--text-muted)", lineHeight: 1.5 }}>
        LLM pipeline stages (provider calls). This is not the GitHub HTTP trace—those requests happen inside each
        stage when the agent reads the repo or posts comments.
      </p>
      {audits.length === 0 ? (
        <p style={{ margin: "0 0 0.85rem", fontSize: "0.85rem", color: "var(--text-muted)" }}>
          {pipelineEmptyHint ??
            "No pipeline stages recorded yet. If the review is still running, refresh after it completes."}
        </p>
      ) : null}
      {hasChunking && chunkingPlan ? <ChunkingCallout plan={chunkingPlan} /> : null}
      {audits.length > 0 ? (
        <div style={{ marginBottom: "0.75rem", display: "flex", flexDirection: "column" }}>
          {audits.map((audit, index) => {
            const estimatedCostUsd = stageCostByAuditId.get(audit.id) ?? null;
            return (
              <StageCard
                key={audit.id}
                audit={audit}
                debugArtifacts={debugArtifacts}
                defaultOpen={AUTO_OPEN_STAGES.has(audit.stage)}
                isLast={index === audits.length - 1 && !isInFlight}
                estimatedCostUsd={estimatedCostUsd}
              />
            );
          })}
          {isInFlight ? <LiveStageProgress label={pendingMeta.label} icon={pendingMeta.icon} /> : null}
        </div>
      ) : isInFlight ? (
        <LiveStageProgress label={pendingMeta.label} icon={pendingMeta.icon} />
      ) : (
        <div
          style={{
            marginBottom: "0.75rem",
            border: "2px dashed var(--border-strong)",
            borderRadius: "var(--radius-md)",
            padding: "1rem",
            background: "var(--card-muted)",
          }}
        >
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.75rem" }}>
            No completed step available for this run yet.
          </p>
        </div>
      )}
      <BottomPanelSummary
        audits={audits}
        stageEstimatedCostUsd={stageEstimatedCostUsd}
        postedFindingsCount={postedFindingsCount}
        pipelineStagedFindingsPeak={pipelineStagedFindingsPeak}
        isInFlight={Boolean(isInFlight)}
        nowMs={nowMs}
      />
    </div>
  );
}

// Backward-compatible export while callers migrate to the clearer name.
export const ActionChain = ReviewPipeline;
