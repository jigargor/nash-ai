"use client";

import { useState } from "react";

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

function getRaw(meta: Record<string, unknown> | null, key: string): unknown {
  return meta?.[key] ?? undefined;
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
  const riskLabels = (getRaw(meta, "risk_labels") as string[] | undefined) ?? [];
  const reason = getRaw(meta, "reason") as string | undefined;
  const fileClasses = (getRaw(meta, "file_classes") as Record<string, number> | undefined) ?? {};
  const reviewSurface = getRaw(meta, "review_surface") as number | undefined;

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
        {reviewSurface != null && (
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            · files reviewed: <strong style={{ color: "var(--text-primary)" }}>{reviewSurface}</strong>
          </span>
        )}
      </div>
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

function PrimaryBody({ meta }: { meta: Record<string, unknown> | null }) {
  const sysTokens = getRaw(meta, "system_prompt_tokens") as number | undefined;
  const userTokens = getRaw(meta, "user_prompt_tokens") as number | undefined;
  const excerpt = getRaw(meta, "output_summary_excerpt") as string | undefined;
  const contextLayers = getRaw(meta, "context_layers") as Record<string, unknown> | undefined;
  const layerUsage = contextLayers?.layer_token_usage as Record<string, number> | undefined;
  const dropped = contextLayers?.dropped_segments as string[] | undefined;

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
        <p style={{ margin: 0, fontSize: "0.75rem", color: "#fb923c" }}>
          ⚠ {dropped.length} context segment{dropped.length !== 1 ? "s" : ""} dropped (token budget)
        </p>
      )}
      {excerpt && (
        <blockquote
          style={{
            margin: 0,
            borderLeft: "2px solid var(--border-strong)",
            paddingLeft: "0.75rem",
            fontSize: "0.78rem",
            color: "var(--text-muted)",
            fontStyle: "italic",
          }}
        >
          {excerpt}
        </blockquote>
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

// ---------------------------------------------------------------------------
// Single stage card
// ---------------------------------------------------------------------------

function StageCard({
  audit,
  debugArtifacts,
  defaultOpen,
  isLast,
}: {
  audit: ReviewModelAudit;
  debugArtifacts: Record<string, unknown> | null;
  defaultOpen: boolean;
  isLast: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const { label, icon, color } = stageMeta(audit.stage);
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
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
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
                  {audit.findings_count} finding{audit.findings_count !== 1 ? "s" : ""}
                  {audit.accepted_findings_count != null && audit.accepted_findings_count !== audit.findings_count
                    ? ` → ${audit.accepted_findings_count} kept`
                    : ""}
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

function ChunkingCallout({ plan }: { plan: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const chunks = (plan.chunks as string[] | undefined) ?? [];
  const skipped = (plan.skipped_files as string[] | undefined) ?? [];
  const isPartial = plan.is_partial as boolean | undefined;
  const coverageNote = plan.coverage_note as string | undefined;

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
            {skipped.length > 0 && <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>{skipped.length} file{skipped.length !== 1 ? "s" : ""} skipped</span>}
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
            {skipped.length > 0 && <span style={{ fontSize: "0.72rem", color: "#fb923c" }}>⚠ {skipped.length} files not reviewed</span>}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Token summary footer
// ---------------------------------------------------------------------------

function TokenSummary({
  audits,
  costUsd,
  postedFindingsCount,
}: {
  audits: ReviewModelAudit[];
  costUsd: string | null;
  postedFindingsCount: number;
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
  const showCost = Boolean(costUsd);

  return (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <div style={{ width: "24px", flexShrink: 0 }} />
      <div style={{ flex: 1, borderTop: "1px solid var(--border)", paddingTop: "0.6rem", display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center" }}>
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
        <span style={{ marginLeft: "auto", display: "inline-flex", gap: "0.65rem", alignItems: "center", flexWrap: "wrap" }}>
          {showCost ? (
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Est. cost: <strong style={{ color: "var(--accent)" }}>${costUsd}</strong>
            </span>
          ) : null}
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            Findings: <strong style={{ color: "var(--text-primary)" }}>{postedFindingsCount}</strong>
          </span>
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ActionChain component
// ---------------------------------------------------------------------------

interface ActionChainProps {
  audits: ReviewModelAudit[];
  debugArtifacts: Record<string, unknown> | null;
  costUsd?: string | null;
  /** Final posted findings count (matches PR review summary). */
  postedFindingsCount: number;
  /** Shown when there are no model-audit rows (e.g. still running or audits not persisted). */
  pipelineEmptyHint?: string | null;
}

const AUTO_OPEN_STAGES = new Set(["primary", "challenger", "tie_break"]);

export function ActionChain({
  audits,
  debugArtifacts,
  costUsd,
  postedFindingsCount,
  pipelineEmptyHint,
}: ActionChainProps) {
  const chunkingPlan = debugArtifacts?.chunking_plan as Record<string, unknown> | undefined;
  const hasChunking = chunkingPlan && Array.isArray(chunkingPlan.chunks) && (chunkingPlan.chunks as unknown[]).length > 1;

  // Insert chunking callout before the first chunk_review stage
  const firstChunkIdx = audits.findIndex((a) => a.stage === "chunk_review");

  return (
    <div
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        padding: "1rem",
      }}
    >
      <p style={{ margin: "0 0 0.75rem", fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>
        Action chain
      </p>
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
      <div>
        {audits.map((audit, i) => (
          <div key={audit.id}>
            {hasChunking && i === firstChunkIdx && <ChunkingCallout plan={chunkingPlan!} />}
            <StageCard
              audit={audit}
              debugArtifacts={debugArtifacts}
              defaultOpen={AUTO_OPEN_STAGES.has(audit.stage)}
              isLast={i === audits.length - 1}
            />
          </div>
        ))}
      </div>
      <TokenSummary audits={audits} costUsd={costUsd ?? null} postedFindingsCount={postedFindingsCount} />
    </div>
  );
}
