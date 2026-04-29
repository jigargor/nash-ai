"use client";

import { useState } from "react";

import { Panel } from "@/components/ui/panel";
import { useDeleteUserKey, useUpsertUserKey, useUserKeys } from "@/hooks/use-user-keys";
import type { KeyStatus } from "@/lib/api/user-keys";

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  openai: "OpenAI",
};

const CODEREVIEW_GENERATOR_PROMPT = `You are generating .codereview.yml for Nash AI.

Output contract:
- Return only valid YAML (no markdown, no explanation).
- Include keys: confidence_threshold, severity_threshold, categories, review_drafts,
  max_findings_per_pr, prompt_additions, ignore_paths, model, max_mode, budgets,
  layered_context_enabled, partial_review_mode_enabled, partial_review_changed_lines_threshold,
  summarization_enabled, max_summary_calls_per_review, generated_paths, vendor_paths, chunking.

Policy:
- Prioritize security + correctness findings.
- Keep defaults practical for ongoing PR traffic (balanced precision/cost).
- If recent PRs are large, increase chunking/budget caps moderately.
- If dismissal rate is high, raise confidence threshold and reduce max findings.
- Keep generated/vendor exclusions in place.

Context:
- Repo: {{owner}}/{{repo}}
- Frameworks: {{frameworks}}
- Last 30d PR stats (Railway): {{telemetry_summary}}
- User preference: {{risk_profile}}`;

const CODEREVIEW_GENERATOR_SKILLFILE = `# Skill: codereview-yaml-generator

## Purpose
Generate high-signal .codereview.yml configs for Nash AI repositories.

## Inputs
- owner, repo, installation_id
- detected frameworks
- recent repo telemetry (tokens, latency, finding outcomes)
- user risk/cost preference

## Rules
- Return YAML only.
- Never include secrets or tokens.
- Use bounded thresholds and token budgets.
- Prefer correctness/security over style noise.
- Validate parseability before returning.

## Output fields
- confidence_threshold
- severity_threshold
- categories
- max_findings_per_pr
- model and max_mode
- budgets + chunking
- prompt_additions

## Adaptation logic
- large PRs => increase proactive_threshold_tokens and total_cap safely
- high dismiss rate => raise confidence_threshold
- low signal/noise and low cost pressure => widen categories slightly
`;

const RELEASE_GUARDRAILS_PROMPT = `Write prompt_additions for .codereview.yml that enforce:
- evidence-backed findings only
- no style-only comments before material risk
- include minimal remediation suggestions
- avoid duplicate findings across related hunks`;

function KeyRow({ keyStatus }: { keyStatus: KeyStatus }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const upsert = useUpsertUserKey();
  const remove = useDeleteUserKey();

  async function handleSave() {
    setError(null);
    try {
      await upsert.mutateAsync({ provider: keyStatus.provider, api_key: value });
      setValue("");
      setEditing(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save key");
    }
  }

  async function handleDelete() {
    setError(null);
    try {
      await remove.mutateAsync(keyStatus.provider);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to remove key");
    }
  }

  const label = PROVIDER_LABELS[keyStatus.provider] ?? keyStatus.provider;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
        padding: "0.75rem 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <span style={{ flex: 1, fontWeight: 500 }}>{label}</span>
        <span
          style={{
            fontSize: "0.75rem",
            padding: "0.15rem 0.5rem",
            borderRadius: "999px",
            background: keyStatus.has_key ? "var(--color-success-bg, #d1fae5)" : "var(--color-muted-bg, #f3f4f6)",
            color: keyStatus.has_key ? "var(--color-success, #065f46)" : "var(--text-muted)",
          }}
        >
          {keyStatus.has_key ? "Connected" : "Not set"}
        </span>
        <button className="button button-ghost" style={{ fontSize: "0.8rem" }} onClick={() => setEditing((e) => !e)}>
          {editing ? "Cancel" : keyStatus.has_key ? "Update" : "Add key"}
        </button>
        {keyStatus.has_key && !editing && (
          <button
            className="button button-ghost"
            style={{ fontSize: "0.8rem", color: "var(--color-danger, #dc2626)" }}
            onClick={handleDelete}
            disabled={remove.isPending}
          >
            {remove.isPending ? "Removing…" : "Remove"}
          </button>
        )}
      </div>

      {editing && (
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <input
            type="password"
            autoComplete="off"
            placeholder={`Enter your ${label} API key`}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            style={{ flex: 1, padding: "0.4rem 0.6rem", borderRadius: "6px", border: "1px solid var(--border)", fontSize: "0.875rem" }}
          />
          <button
            className="button button-primary"
            style={{ fontSize: "0.8rem" }}
            onClick={handleSave}
            disabled={upsert.isPending || value.trim().length < 20}
          >
            {upsert.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      )}

      {error && <p style={{ color: "var(--color-danger, #dc2626)", fontSize: "0.8rem", margin: 0 }}>{error}</p>}
    </div>
  );
}

export function ApiKeysPanel() {
  const { data, isLoading, error } = useUserKeys();
  const [copiedLabel, setCopiedLabel] = useState<string | null>(null);

  async function handleCopy(label: string, text: string): Promise<void> {
    await navigator.clipboard.writeText(text);
    setCopiedLabel(label);
    window.setTimeout(() => setCopiedLabel((current) => (current === label ? null : current)), 1200);
  }

  return (
    <Panel>
      <h2 style={{ marginTop: 0 }}>API Keys</h2>
      <p style={{ color: "var(--text-muted)" }}>
        Store your own provider API keys to use instead of the shared defaults. Keys are encrypted at rest (Fernet AES-128)
        and never returned in plain text.
      </p>

      {isLoading && <p style={{ color: "var(--text-muted)" }}>Loading…</p>}
      {error && <p style={{ color: "var(--color-danger, #dc2626)" }}>Failed to load key status.</p>}

      {data && (
        <div>
          {data.map((keyStatus) => (
            <KeyRow key={keyStatus.provider} keyStatus={keyStatus} />
          ))}
        </div>
      )}

      <div style={{ marginTop: "1rem", borderTop: "1px solid var(--border)", paddingTop: "0.9rem", display: "grid", gap: "0.8rem" }}>
        <h3 style={{ margin: 0 }}>Personalize</h3>
        <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.875rem" }}>
          Use these one-click prompt + skillfile templates to regenerate repository-specific{" "}
          <code>.codereview.yml</code> policies from production behavior.
        </p>

        <div style={{ display: "grid", gap: "0.45rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
            <strong style={{ fontSize: "0.9rem" }}>Generator prompt</strong>
            <button className="button button-ghost" style={{ fontSize: "0.8rem" }} onClick={() => void handleCopy("prompt", CODEREVIEW_GENERATOR_PROMPT)}>
              {copiedLabel === "prompt" ? "Copied" : "Copy prompt"}
            </button>
          </div>
          <pre style={{ margin: 0, maxHeight: "14rem", overflow: "auto", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "0.65rem", background: "var(--card-muted)", fontSize: "0.75rem", lineHeight: 1.4 }}>
            {CODEREVIEW_GENERATOR_PROMPT}
          </pre>
        </div>

        <div style={{ display: "grid", gap: "0.45rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
            <strong style={{ fontSize: "0.9rem" }}>Skillfile template</strong>
            <button className="button button-ghost" style={{ fontSize: "0.8rem" }} onClick={() => void handleCopy("skill", CODEREVIEW_GENERATOR_SKILLFILE)}>
              {copiedLabel === "skill" ? "Copied" : "Copy skillfile"}
            </button>
          </div>
          <pre style={{ margin: 0, maxHeight: "14rem", overflow: "auto", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "0.65rem", background: "var(--card-muted)", fontSize: "0.75rem", lineHeight: 1.4 }}>
            {CODEREVIEW_GENERATOR_SKILLFILE}
          </pre>
        </div>

        <div style={{ display: "grid", gap: "0.45rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
            <strong style={{ fontSize: "0.9rem" }}>Bonus prompt additions block</strong>
            <button className="button button-ghost" style={{ fontSize: "0.8rem" }} onClick={() => void handleCopy("guardrails", RELEASE_GUARDRAILS_PROMPT)}>
              {copiedLabel === "guardrails" ? "Copied" : "Copy block"}
            </button>
          </div>
          <pre style={{ margin: 0, maxHeight: "10rem", overflow: "auto", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "0.65rem", background: "var(--card-muted)", fontSize: "0.75rem", lineHeight: 1.4 }}>
            {RELEASE_GUARDRAILS_PROMPT}
          </pre>
        </div>
      </div>
    </Panel>
  );
}
