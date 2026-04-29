"use client";

import type { ExternalEvalDetail } from "@/lib/api/external-evals";

function formatCurrency(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "$0.0000";
  return `$${numeric.toFixed(4)}`;
}

function statusTone(status: string): string {
  if (status === "done" || status === "complete" || status === "synthesized") return "#34d399";
  if (status === "running" || status === "analyzing" || status === "scanning" || status === "synthesizing")
    return "#60a5fa";
  if (status === "skipped" || status === "partial") return "#f59e0b";
  if (status === "failed" || status === "canceled") return "#f43f5e";
  return "var(--text-muted)";
}

interface ExternalEvalActionChainProps {
  detail: ExternalEvalDetail;
}

export function ExternalEvalActionChain({ detail }: ExternalEvalActionChainProps) {
  const prepass = detail.prepass_metadata ?? {};
  const shards = detail.shards ?? [];
  const completed = shards.filter((item) => item.status === "done" || item.status === "synthesized").length;

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        padding: "0.8rem",
        background: "var(--card-muted)",
        display: "grid",
        gap: "0.7rem",
      }}
    >
      <p style={{ margin: 0, fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        Tour Pipeline
      </p>

      <article style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "0.6rem 0.7rem", background: "var(--card)" }}>
        <p style={{ margin: 0, fontWeight: 600 }}>1) Prepass Scan</p>
        <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)", fontSize: "0.82rem" }}>
          model: {String(prepass.cheap_pass_model ?? "n/a")} · tier: {String(prepass.service_tier ?? "n/a")} ·
          recommended team: {String(prepass.recommended_team_size ?? "n/a")}
        </p>
      </article>

      <article style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "0.6rem 0.7rem", background: "var(--card)" }}>
        <p style={{ margin: 0, fontWeight: 600 }}>2) Shard Analysis</p>
        <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)", fontSize: "0.82rem" }}>
          {completed}/{shards.length} shards complete
        </p>
        <div style={{ marginTop: "0.45rem", display: "grid", gap: "0.35rem" }}>
          {shards.map((shard) => (
            <div key={shard.id} style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", fontSize: "0.78rem" }}>
              <span style={{ color: "var(--text-muted)" }}>
                {shard.shard_key} · {shard.model_tier} · files {shard.file_count}
              </span>
              <span style={{ color: statusTone(shard.status), fontWeight: 600 }}>
                {shard.status} · {shard.findings_count} findings · {formatCurrency(shard.cost_usd)}
              </span>
            </div>
          ))}
        </div>
      </article>

      <article style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "0.6rem 0.7rem", background: "var(--card)" }}>
        <p style={{ margin: 0, fontWeight: 600 }}>3) Synthesis & Output</p>
        <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)", fontSize: "0.82rem" }}>
          status: <strong style={{ color: statusTone(detail.status) }}>{detail.status}</strong> · total findings{" "}
          {detail.findings_count} · tokens {detail.tokens_used} · cost {formatCurrency(detail.cost_usd)}
        </p>
      </article>
    </div>
  );
}
