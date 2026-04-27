"use client";

import { ApiKeysPanel } from "@/components/settings/api-keys-panel";
import { CodeReviewConfigPanel } from "@/components/settings/code-review-config-panel";
import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function SettingsPage() {
  const currentUser = useCurrentUser();

  if (currentUser.isLoading) {
    return <StateBlock title="Loading settings" description="Fetching account settings." />;
  }

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      <Panel>
        <h2 style={{ marginTop: 0 }}>Account</h2>
        <p style={{ color: "var(--text-muted)", marginBottom: "0.75rem" }}>
          {currentUser.data?.authenticated
            ? `Signed in as @${currentUser.data.user?.login ?? "user"}`
            : "Session not authenticated"}
        </p>
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- session cookie clear via API */}
        <a className="button button-ghost" href="/api/v1/auth/logout" style={{ fontSize: "0.875rem" }}>
          Logout
        </a>
      </Panel>

      <ApiKeysPanel />

      <CodeReviewConfigPanel />
    </section>
  );
}
