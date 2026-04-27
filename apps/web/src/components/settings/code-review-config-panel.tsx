"use client";

import { useState } from "react";

import { Panel } from "@/components/ui/panel";
import { useCodeReviewConfig } from "@/hooks/use-code-review-config";
import { useInstallations } from "@/hooks/use-installations";
import { useRepos } from "@/hooks/use-repos";

const DOCS_EXAMPLE_URL =
  "https://github.com/jigargor/nash-ai/blob/main/.codereview.yml";

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
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        View the <code>.codereview.yml</code> file from any of your connected repositories. This
        file controls which model, confidence thresholds, and review categories the agent uses.
      </p>

      {isLoadingRepos && <p style={{ color: "var(--text-muted)" }}>Loading repositories…</p>}

      {!isLoadingRepos && repoList.length === 0 && (
        <p style={{ color: "var(--text-muted)" }}>
          No repositories found. Install the GitHub App on a repository first.
        </p>
      )}

      {!isLoadingRepos && repoList.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <select
            value={selectedRepo || activeRepo || ""}
            onChange={(e) => setSelectedRepo(e.target.value)}
            style={{
              padding: "0.4rem 0.6rem",
              borderRadius: "6px",
              border: "1px solid var(--border)",
              fontSize: "0.875rem",
              background: "var(--surface)",
              color: "var(--text)",
              maxWidth: "400px",
            }}
          >
            {repoList.map((r) => (
              <option key={r.repo_full_name} value={r.repo_full_name}>
                {r.repo_full_name}
              </option>
            ))}
          </select>

          {config.isLoading && (
            <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>Loading config…</p>
          )}

          {config.isError && (
            <p style={{ color: "var(--color-danger, #dc2626)", fontSize: "0.875rem" }}>
              Failed to load configuration.
            </p>
          )}

          {config.data && !config.data.found && (
            <div>
              <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", margin: 0 }}>
                No <code>.codereview.yml</code> found in this repository — reviews will use default
                settings.{" "}
                <a href={DOCS_EXAMPLE_URL} target="_blank" rel="noreferrer">
                  View example config
                </a>
              </p>
            </div>
          )}

          {config.data?.found && config.data.yaml_text && (
            <pre
              style={{
                background: "var(--surface-elevated, #f6f8fa)",
                border: "1px solid var(--border)",
                borderRadius: "6px",
                padding: "0.75rem 1rem",
                fontSize: "0.8rem",
                lineHeight: 1.5,
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
