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
    </Panel>
  );
}
