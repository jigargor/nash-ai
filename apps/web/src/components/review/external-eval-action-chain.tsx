"use client";

import type { ExternalEvalDetail } from "@/lib/api/external-evals";

type StepTone = "done" | "active" | "queued" | "skipped" | "failed";

function formatCurrency(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "$0.0000";
  return `$${numeric.toFixed(4)}`;
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function toneColor(tone: StepTone): string {
  if (tone === "done") return "#34d399";
  if (tone === "active") return "#60a5fa";
  if (tone === "skipped") return "#f59e0b";
  if (tone === "failed") return "#f43f5e";
  return "var(--text-muted)";
}

function shardTone(status: string): string {
  if (status === "done" || status === "synthesized") return "#34d399";
  if (status === "running" || status === "queued") return "#60a5fa";
  if (status === "skipped") return "#f59e0b";
  if (status === "failed" || status === "canceled") return "#f43f5e";
  return "var(--text-muted)";
}

function metaString(meta: Record<string, unknown>, key: string): string | null {
  const value = meta[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function metaNumber(meta: Record<string, unknown>, key: string): number | null {
  const value = meta[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function hasTerminalStatus(status: string): boolean {
  return ["complete", "partial", "failed", "canceled"].includes(status);
}

function statusStepTone(status: string, activeStatus: string): StepTone {
  if (status === "failed" || status === "canceled") return "failed";
  if (status === activeStatus) return "active";
  if (hasTerminalStatus(status)) return status === "partial" ? "skipped" : "done";
  return "queued";
}

interface ExternalEvalActionChainProps {
  detail: ExternalEvalDetail;
}

export function ExternalEvalActionChain({ detail }: ExternalEvalActionChainProps) {
  const prepass = detail.prepass_metadata ?? {};
  const shards = detail.shards ?? [];
  const completed = shards.filter((item) => item.status === "done" || item.status === "synthesized").length;
  const finished = shards.filter((item) => ["done", "synthesized", "skipped", "failed", "canceled"].includes(item.status)).length;
  const riskyPaths = metaNumber(prepass, "risky_paths_count") ?? (Array.isArray(prepass.risky_paths) ? prepass.risky_paths.length : 0);
  const promptInjectionPaths = Array.isArray(prepass.prompt_injection_paths) ? prepass.prompt_injection_paths.length : 0;
  const fillerPaths = Array.isArray(prepass.filler_paths) ? prepass.filler_paths.length : 0;
  const prepassEstimatedTokens = metaNumber(prepass, "estimated_tokens") ?? detail.estimated_tokens;
  const prepassEstimatedCost = metaString(prepass, "estimated_cost_usd") ?? detail.estimated_cost_usd;
  const shardAnalysisTone: StepTone =
    detail.status === "failed" || detail.status === "canceled"
      ? "failed"
      : detail.status === "analyzing" || shards.some((item) => item.status === "queued" || item.status === "running")
        ? "active"
        : shards.length > 0 && finished === shards.length
          ? detail.status === "partial"
            ? "skipped"
            : "done"
          : ["synthesizing", "complete", "partial"].includes(detail.status)
            ? "done"
            : "queued";
  const steps = [
    {
      key: "estimate",
      index: "1",
      title: "Resolve & Estimate",
      tone: "done" as StepTone,
      summary: `${detail.owner}/${detail.repo}@${detail.target_ref}`,
      body: (
        <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.78rem" }}>
          Estimate: <strong style={{ color: "var(--text-primary)" }}>{formatInteger(detail.estimated_tokens)}</strong> tokens -{" "}
          <strong style={{ color: "var(--text-primary)" }}>{formatCurrency(detail.estimated_cost_usd)}</strong> cost window.
        </p>
      ),
    },
    {
      key: "prepass",
      index: "2",
      title: "Heuristic Prepass",
      tone: prepass ? statusStepTone(detail.status, "scanning") : "queued",
      summary: `model ${String(prepass.cheap_pass_model ?? "pending")} - tier ${String(prepass.service_tier ?? "pending")}`,
      body: (
        <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.78rem" }}>
          Inspected <strong style={{ color: "var(--text-primary)" }}>{formatInteger(Number(prepass.inspected_file_count ?? 0))}</strong> files -{" "}
          risky paths <strong style={{ color: "var(--text-primary)" }}>{formatInteger(riskyPaths)}</strong> - prompt markers{" "}
          <strong style={{ color: "var(--text-primary)" }}>{promptInjectionPaths}</strong> - filler{" "}
          <strong style={{ color: "var(--text-primary)" }}>{fillerPaths}</strong>. Repo-side estimate remains{" "}
          <strong style={{ color: "var(--text-primary)" }}>{formatInteger(prepassEstimatedTokens)}</strong> tokens /{" "}
          <strong style={{ color: "var(--text-primary)" }}>{formatCurrency(prepassEstimatedCost)}</strong>.
        </p>
      ),
    },
    {
      key: "shards",
      index: "3",
      title: "Shard Analysis",
      tone: shardAnalysisTone,
      summary: `${completed}/${shards.length} shards complete`,
      body: (
        <div style={{ marginTop: "0.2rem", display: "grid", gap: "0.35rem" }}>
          {shards.length === 0 ? (
            <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.78rem" }}>Waiting for the prepass plan to create shards.</p>
          ) : (
            shards.map((shard) => (
              <div key={shard.id} style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", fontSize: "0.78rem" }}>
                <span style={{ color: "var(--text-muted)" }}>
                  {shard.shard_key} - {shard.model_tier} - files {shard.file_count}
                </span>
                <span style={{ color: shardTone(shard.status), fontWeight: 600 }}>
                  {shard.status} - {shard.findings_count} findings - {formatInteger(shard.tokens_used)} tok - {formatCurrency(shard.cost_usd)}
                </span>
              </div>
            ))
          )}
        </div>
      ),
    },
    {
      key: "synthesis",
      index: "4",
      title: "Synthesis & Findings",
      tone: statusStepTone(detail.status, "synthesizing"),
      summary: `${detail.findings_count} findings - ${formatInteger(detail.tokens_used)} tokens - ${formatCurrency(detail.cost_usd)}`,
      body: (
        <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.78rem" }}>
          Status: <strong style={{ color: toneColor(statusStepTone(detail.status, "synthesizing")) }}>{detail.status}</strong> - total findings{" "}
          <strong style={{ color: "var(--text-primary)" }}>{detail.findings_count}</strong> - used{" "}
          <strong style={{ color: "var(--text-primary)" }}>{formatInteger(detail.tokens_used)}</strong> tokens /{" "}
          <strong style={{ color: "var(--text-primary)" }}>{formatCurrency(detail.cost_usd)}</strong>.
        </p>
      ),
    },
  ];

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        padding: "1rem",
        background: "var(--card)",
        display: "grid",
        gap: "0.6rem",
      }}
    >
      <p style={{ margin: 0, fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>
        Entire repo review pipeline
      </p>
      <p style={{ margin: "0 0 0.2rem", color: "var(--text-muted)", fontSize: "0.78rem" }}>
        Deterministic prepass, parallel shards, and final synthesis for full repository review.
      </p>

      <div style={{ display: "flex", flexDirection: "column" }}>
        {steps.map((step, index) => {
          const color = toneColor(step.tone);
          const isLast = index === steps.length - 1;
          return (
            <div key={step.key} style={{ display: "flex", gap: "0.75rem" }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0, width: "24px" }}>
                <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: `${color}22`, border: `2px solid ${color}66`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.75rem", fontWeight: 700, flexShrink: 0 }}>
                  {step.index}
                </div>
                {!isLast ? (
                  <div style={{ width: "1px", flex: 1, minHeight: "18px", borderLeft: "1px dashed var(--border-strong)", marginTop: "4px" }} />
                ) : null}
              </div>
              <article style={{ flex: 1, marginBottom: isLast ? 0 : "0.55rem" }}>
                <div
                  style={{
                    border: `1px solid ${step.tone === "queued" ? "var(--border)" : color + "33"}`,
                    borderRadius: "var(--radius-md)",
                    padding: "0.55rem 0.75rem",
                    background: step.tone === "active" ? `${color}0a` : "var(--card-muted)",
                    display: "grid",
                    gap: "0.4rem",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem", flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 700, color: "var(--text-primary)", fontSize: "0.86rem" }}>{step.title}</span>
                    <span style={{ color, fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                      {step.tone}
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                    {step.tone === "active" ? (
                      <div className="orbit-loader" aria-hidden>
                        <span className="orbit-dot orbit-dot-1" />
                        <span className="orbit-dot orbit-dot-2" />
                        <span className="orbit-dot orbit-dot-3" />
                      </div>
                    ) : null}
                    <span style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>{step.summary}</span>
                  </div>
                  {step.body}
                </div>
              </article>
            </div>
          );
        })}
      </div>

      <style jsx>{`
        .orbit-loader {
          position: relative;
          width: 1rem;
          height: 1rem;
          animation: orbit-spin 1.4s linear infinite;
          flex: 0 0 auto;
        }
        .orbit-dot {
          position: absolute;
          width: 0.24rem;
          height: 0.24rem;
          border-radius: 999px;
          background: var(--accent);
          top: 50%;
          left: 50%;
          margin-top: -0.12rem;
          margin-left: -0.12rem;
        }
        .orbit-dot-1 {
          transform: translateY(-0.45rem);
        }
        .orbit-dot-2 {
          transform: rotate(120deg) translateY(-0.45rem);
        }
        .orbit-dot-3 {
          transform: rotate(240deg) translateY(-0.45rem);
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
