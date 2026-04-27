"use client";

import { useState } from "react";

import { Panel } from "@/components/ui/panel";
import { useCodeReviewConfig } from "@/hooks/use-code-review-config";
import { useInstallations } from "@/hooks/use-installations";
import { useRepos } from "@/hooks/use-repos";

const DOCS_EXAMPLE_URL = "https://github.com/jigargor/nash-ai/blob/main/.codereview.yml";

// ---------------------------------------------------------------------------
// Collapsible tree renderer
// ---------------------------------------------------------------------------

type ConfigValue = string | number | boolean | null | ConfigValue[] | Record<string, ConfigValue>;

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function isExpandable(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  return false;
}

interface NodeProps {
  label: string;
  value: unknown;
  depth: number;
  defaultOpen?: boolean;
}

function ConfigNode({ label, value, depth, defaultOpen = false }: NodeProps) {
  const [open, setOpen] = useState(defaultOpen);
  const expandable = isExpandable(value);
  const isArr = Array.isArray(value);
  const isObj = !isArr && typeof value === "object" && value !== null;

  const indent = depth * 16;
  const isTopLevel = depth === 0;

  // Scalar leaf
  if (!expandable) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: "0.4rem",
          paddingLeft: indent + 20,
          paddingTop: "0.2rem",
          paddingBottom: "0.2rem",
        }}
      >
        <span style={{ color: "var(--text-muted)", fontSize: "0.8rem", fontFamily: "monospace" }}>
          {label}:
        </span>
        <span
          style={{
            color:
              typeof value === "boolean"
                ? "var(--accent)"
                : typeof value === "number"
                  ? "#60a5fa"
                  : "var(--text-primary)",
            fontSize: "0.8rem",
            fontFamily: "monospace",
          }}
        >
          {formatScalar(value)}
        </span>
      </div>
    );
  }

  // Array of scalars — render inline as tags
  if (isArr && !(value as unknown[]).some((v) => isExpandable(v))) {
    const items = value as unknown[];
    return (
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: "0.4rem",
          paddingLeft: indent + 20,
          paddingTop: "0.2rem",
          paddingBottom: "0.2rem",
          flexWrap: "wrap",
        }}
      >
        <span style={{ color: "var(--text-muted)", fontSize: "0.8rem", fontFamily: "monospace", flexShrink: 0 }}>
          {label}:
        </span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
          {items.map((item, i) => (
            <span
              key={i}
              style={{
                background: "var(--card-muted)",
                border: "1px solid var(--border-strong)",
                borderRadius: "4px",
                padding: "0.05rem 0.4rem",
                fontSize: "0.75rem",
                fontFamily: "monospace",
                color: "var(--text-primary)",
              }}
            >
              {formatScalar(item)}
            </span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ paddingTop: isTopLevel ? "0.1rem" : 0 }}>
      {/* Header row */}
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          width: "100%",
          textAlign: "left",
          background: isTopLevel
            ? open
              ? "rgba(245,158,11,0.07)"
              : "rgba(245,158,11,0.03)"
            : "transparent",
          border: "none",
          borderRadius: "var(--radius-sm)",
          paddingLeft: indent,
          paddingTop: isTopLevel ? "0.45rem" : "0.2rem",
          paddingBottom: isTopLevel ? "0.45rem" : "0.2rem",
          paddingRight: "0.5rem",
          cursor: "pointer",
          color: "inherit",
          borderTop: isTopLevel ? "1px solid var(--border)" : "none",
          marginTop: isTopLevel ? "0.25rem" : 0,
        }}
      >
        {/* Arrow */}
        <span
          style={{
            fontSize: "0.6rem",
            color: "var(--accent)",
            display: "inline-block",
            transition: "transform 0.15s",
            transform: open ? "rotate(90deg)" : "rotate(0deg)",
            userSelect: "none",
            width: "12px",
            textAlign: "center",
          }}
        >
          ▶
        </span>
        <span
          style={{
            fontFamily: "monospace",
            fontSize: isTopLevel ? "0.85rem" : "0.8rem",
            fontWeight: isTopLevel ? 600 : 400,
            color: isTopLevel ? "var(--text-primary)" : "var(--text-muted)",
          }}
        >
          {label}
        </span>
        {!open && (
          <span
            style={{
              fontSize: "0.7rem",
              color: "var(--text-muted)",
              opacity: 0.6,
              marginLeft: "0.25rem",
            }}
          >
            {isArr
              ? `[${(value as unknown[]).length}]`
              : `{${Object.keys(value as object).length}}`}
          </span>
        )}
      </button>

      {/* Children */}
      {open && (
        <div
          style={{
            borderLeft: depth === 0 ? "2px solid var(--border-strong)" : "1px solid var(--border)",
            marginLeft: indent + 5,
            paddingLeft: "0.5rem",
            marginBottom: isTopLevel ? "0.25rem" : 0,
          }}
        >
          {isArr
            ? (value as unknown[]).map((item, i) => {
                if (isExpandable(item) && typeof item === "object" && item !== null) {
                  return (
                    <ConfigNode
                      key={i}
                      label={`[${i}]`}
                      value={item}
                      depth={depth + 1}
                    />
                  );
                }
                return (
                  <div
                    key={i}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.3rem",
                      paddingTop: "0.15rem",
                      paddingBottom: "0.15rem",
                    }}
                  >
                    <span style={{ color: "var(--accent)", fontSize: "0.75rem" }}>–</span>
                    <span
                      style={{
                        fontFamily: "monospace",
                        fontSize: "0.8rem",
                        color: "var(--text-primary)",
                      }}
                    >
                      {formatScalar(item)}
                    </span>
                  </div>
                );
              })
            : Object.entries(value as Record<string, unknown>).map(([k, v]) => (
                <ConfigNode key={k} label={k} value={v} depth={depth + 1} />
              ))}
        </div>
      )}
    </div>
  );
}

interface ConfigTreeProps {
  config: Record<string, unknown>;
}

// Key order: show important sections first
const SECTION_ORDER = [
  "model",
  "confidence_threshold",
  "severity_threshold",
  "categories",
  "max_mode",
  "chunking",
  "fast_path",
  "budgets",
  "ignore_paths",
  "max_findings_per_pr",
  "review_drafts",
  "models",
];

function ConfigTree({ config }: ConfigTreeProps) {
  const ordered = [
    ...SECTION_ORDER.filter((k) => k in config),
    ...Object.keys(config).filter((k) => !SECTION_ORDER.includes(k)),
  ];

  return (
    <div
      style={{
        background: "var(--card-muted)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        padding: "0 0.5rem 0.5rem",
        fontSize: "0.85rem",
        maxHeight: "520px",
        overflowY: "auto",
      }}
    >
      {ordered.map((key, i) => (
        <ConfigNode
          key={key}
          label={key}
          value={config[key]}
          depth={0}
          defaultOpen={i < 4}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function CodeReviewConfigPanel() {
  const installations = useInstallations();
  const firstInstallation = installations.data?.[0];
  const installationId = firstInstallation?.installation_id ?? null;

  const repos = useRepos(installationId ?? undefined);
  const repoList = repos.data ?? [];

  const [selectedRepo, setSelectedRepo] = useState<string>("");
  const activeRepo = selectedRepo || repoList[0]?.repo_full_name || null;

  const [owner, repo] = activeRepo ? activeRepo.split("/") : [null, null];
  const config = useCodeReviewConfig(owner ?? null, repo ?? null, installationId);

  const isLoadingRepos = installations.isLoading || repos.isLoading;

  return (
    <Panel>
      <h2 style={{ marginTop: 0 }}>Rule Configuration</h2>
      <p style={{ color: "var(--text-muted)", marginTop: 0, fontSize: "0.875rem" }}>
        The <code style={{ color: "var(--accent)", fontSize: "0.8rem" }}>.codereview.yml</code> file
        from your repository controls which model, confidence thresholds, and review categories the
        agent uses.
      </p>

      {isLoadingRepos && (
        <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>Loading repositories…</p>
      )}

      {!isLoadingRepos && repoList.length === 0 && (
        <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
          No repositories found. Install the GitHub App on a repository first.
        </p>
      )}

      {!isLoadingRepos && repoList.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <select
            value={selectedRepo || activeRepo || ""}
            onChange={(e) => setSelectedRepo(e.target.value)}
            style={{
              padding: "0.4rem 0.6rem",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-strong)",
              fontSize: "0.875rem",
              background: "var(--card-muted)",
              color: "var(--text-primary)",
              maxWidth: "400px",
              cursor: "pointer",
            }}
          >
            {repoList.map((r) => (
              <option key={r.repo_full_name} value={r.repo_full_name}>
                {r.repo_full_name}
              </option>
            ))}
          </select>

          {config.isLoading && (
            <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", margin: 0 }}>
              Loading config…
            </p>
          )}

          {config.isError && (
            <p style={{ color: "var(--severity-critical)", fontSize: "0.875rem", margin: 0 }}>
              Failed to load configuration.
            </p>
          )}

          {config.data && !config.data.found && (
            <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", margin: 0 }}>
              No{" "}
              <code style={{ color: "var(--accent)", fontSize: "0.8rem" }}>.codereview.yml</code>{" "}
              found — reviews use default settings.{" "}
              <a href={DOCS_EXAMPLE_URL} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
                View example
              </a>
            </p>
          )}

          {config.data?.found && config.data.config_json && (
            <ConfigTree config={config.data.config_json} />
          )}

          {/* Fallback to raw text if JSON parse failed but file exists */}
          {config.data?.found && !config.data.config_json && config.data.yaml_text && (
            <pre
              style={{
                background: "var(--card-muted)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-lg)",
                padding: "0.75rem 1rem",
                fontSize: "0.8rem",
                fontFamily: "monospace",
                lineHeight: 1.6,
                color: "var(--text-primary)",
                overflowX: "auto",
                overflowY: "auto",
                maxHeight: "480px",
                margin: 0,
                whiteSpace: "pre",
              }}
            >
              {config.data.yaml_text}
            </pre>
          )}
        </div>
      )}
    </Panel>
  );
}
