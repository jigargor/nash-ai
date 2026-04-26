"use client";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useInstallations } from "@/hooks/use-installations";

export default function SettingsPage() {
  const currentUser = useCurrentUser();
  const installations = useInstallations();

  if (installations.isLoading || currentUser.isLoading) {
    return <StateBlock title="Loading settings" description="Fetching account and installation settings." />;
  }

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      <Panel>
        <h2 style={{ marginTop: 0 }}>Account</h2>
        <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
          {currentUser.data?.authenticated
            ? `Signed in as @${currentUser.data.user?.login ?? "user"}`
            : "Session not authenticated"}
        </p>
      </Panel>

      <Panel>
        <h2 style={{ marginTop: 0 }}>GitHub App Installation</h2>
        <p style={{ color: "var(--text-muted)" }}>
          Active installations: {installations.data?.filter((item) => item.active).length ?? 0}
        </p>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <a className="button button-primary" href="https://github.com/settings/apps" target="_blank" rel="noreferrer">
            Open GitHub settings
          </a>
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- session cookie clear via API */}
          <a className="button button-ghost" href="/api/v1/auth/logout">
            Logout
          </a>
        </div>
      </Panel>

      <Panel>
        <h2 style={{ marginTop: 0 }}>Rule Configuration</h2>
        <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
          Per-repository rule configuration will appear here once rule management endpoints are available.
        </p>
      </Panel>
    </section>
  );
}
