"use client";

import Link from "next/link";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useInstallations } from "@/hooks/use-installations";

export default function RepositoriesPage() {
  const installations = useInstallations();

  if (installations.isLoading) {
    return <StateBlock title="Loading repositories" description="Fetching installation accounts and status." />;
  }

  if (installations.isError) {
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

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      {installations.data.map((installation) => (
        <Panel key={installation.installation_id}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center" }}>
            <div>
              <h3 style={{ margin: 0 }}>
                {installation.account_login} <span style={{ color: "var(--text-muted)" }}>({installation.account_type})</span>
              </h3>
              <p style={{ margin: "0.4rem 0 0", color: "var(--text-muted)" }}>
                Installation #{installation.installation_id}
              </p>
            </div>
            <span className="status-pill">{installation.active ? "Active" : "Suspended"}</span>
          </div>

          <div style={{ marginTop: "0.9rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Link href="/reviews" className="button button-ghost">
              View reviews
            </Link>
            <Link href="/settings" className="button button-ghost">
              Manage settings
            </Link>
          </div>
        </Panel>
      ))}
    </section>
  );
}
