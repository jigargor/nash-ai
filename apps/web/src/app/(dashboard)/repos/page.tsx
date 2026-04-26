"use client";

import Link from "next/link";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useInstallations } from "@/hooks/use-installations";
import { useRepos } from "@/hooks/use-repos";

export default function RepositoriesPage() {
  const installations = useInstallations();
  const repos = useRepos();

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
              <Link href="/settings" className="button button-ghost">
                Manage settings
              </Link>
            </div>
          </Panel>
        );
      })}
    </section>
  );
}
