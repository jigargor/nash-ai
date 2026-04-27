"use client";

import Link from "next/link";
import { useState } from "react";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useInstallations } from "@/hooks/use-installations";
import { useGenerateRepoTemplate } from "@/hooks/use-repo-template";
import { useRepos } from "@/hooks/use-repos";
import { CODEREVIEW_TEMPLATE_EXAMPLE } from "@/lib/api/repos";
import { downloadTextFile } from "@/lib/download-text-file";

export default function RepositoriesPage() {
  const installations = useInstallations();
  const repos = useRepos();
  const generateTemplate = useGenerateRepoTemplate();
  const [statusByRepo, setStatusByRepo] = useState<Record<string, string>>({});

  if (installations.isLoading || repos.isLoading) {
    return <StateBlock title="Loading repositories" description="Fetching installation accounts and status." />;
  }

  if (installations.isError || repos.isError) {
    return <StateBlock title="Failed to load repositories" description="API error while loading installations." />;
  }

  if (!installations.data?.length) {
    return (
      <StateBlock
        title="No repositories connected"
        description="Install the GitHub App on at least one account to start receiving reviews."
        action={
          <a className="button button-primary" href="https://github.com/settings/apps" target="_blank" rel="noreferrer">
            Open GitHub App settings
          </a>
        }
      />
    );
  }

  if (!repos.data?.length) {
    return (
      <StateBlock
        title="No repository review activity yet"
        description="Repository rows are created from review activity. Open or synchronize a pull request to trigger the first run."
      />
    );
  }

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      {repos.data.map((repo) => {
        const installation = installations.data.find((item) => item.installation_id === repo.installation_id);
        const [owner, repoName] = repo.repo_full_name.split("/", 2);
        const repoKey = `${repo.installation_id}:${repo.repo_full_name}`;
        return (
          <Panel key={`${repo.installation_id}:${repo.repo_full_name}`}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center" }}>
              <div>
                <h3 style={{ margin: 0 }}>
                  {repo.repo_full_name}
                </h3>
                <p style={{ margin: "0.4rem 0 0", color: "var(--text-muted)" }}>
                  {installation?.account_login ?? "Installation"} #{repo.installation_id} / latest PR #{repo.latest_pr_number}
                </p>
              </div>
              <span className="status-pill">{repo.latest_status}</span>
            </div>

            <div style={{ marginTop: "0.9rem", display: "flex", gap: "1rem", flexWrap: "wrap", color: "var(--text-muted)" }}>
              <span>{repo.review_count} reviews</span>
              <span>{repo.failed_review_count} failed</span>
              <span>{repo.total_tokens} tokens</span>
              <span>${Number(repo.estimated_cost_usd).toFixed(6)}</span>
            </div>

            <div style={{ marginTop: "0.9rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <Link
                href={`/repos/${repo.repo_full_name}/prs/${repo.latest_pr_number}?reviewId=${repo.latest_review_id}&installationId=${repo.installation_id}`}
                className="button button-ghost"
              >
                Latest review
              </Link>
              <button
                type="button"
                className="button button-ghost"
                onClick={async () => {
                  if (!owner || !repoName) {
                    setStatusByRepo((prev) => ({ ...prev, [repoKey]: "Invalid repository name." }));
                    return;
                  }
                  try {
                    const generated = await generateTemplate.mutateAsync({
                      owner,
                      repo: repoName,
                      installationId: repo.installation_id,
                    });
                    await downloadTextFile(".codereview.yml", generated.config_yaml_text);
                    setStatusByRepo((prev) => ({
                      ...prev,
                      [repoKey]: `Generated with ${generated.provider}/${generated.model} and downloaded.`,
                    }));
                  } catch (error) {
                    const message = error instanceof Error ? error.message : "Failed to generate template.";
                    setStatusByRepo((prev) => ({ ...prev, [repoKey]: message }));
                  }
                }}
                disabled={repo.ai_template_generated || generateTemplate.isPending}
              >
                {repo.ai_template_generated ? "AI template already generated" : "Generate AI .codereview.yml"}
              </button>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void downloadTextFile(".codereview.yml.example", CODEREVIEW_TEMPLATE_EXAMPLE)}
              >
                Download example template
              </button>
              <Link href="/settings" className="button button-ghost">
                Manage settings
              </Link>
            </div>
            {repo.ai_template_generated_at ? (
              <p style={{ marginTop: "0.5rem", color: "var(--text-muted)" }}>
                AI template generated at {new Date(repo.ai_template_generated_at).toLocaleString()}.
              </p>
            ) : null}
            {statusByRepo[repoKey] ? (
              <p style={{ marginTop: "0.5rem", color: "var(--text-muted)" }}>{statusByRepo[repoKey]}</p>
            ) : null}
          </Panel>
        );
      })}
    </section>
  );
}
