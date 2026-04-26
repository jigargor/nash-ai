import Link from "next/link";

import { QueryProvider } from "@/components/providers/query-provider";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", display: "grid", gridTemplateColumns: "260px 1fr" }}>
      <aside
        style={{
          borderRight: "1px solid var(--border)",
          background: "var(--card)",
          padding: "1rem",
        }}
      >
        <h2 style={{ marginTop: 0, fontFamily: "var(--font-instrument-serif)" }}>Nash AI</h2>
        <nav style={{ display: "grid", gap: "0.5rem" }}>
          <Link href="/dashboard">Dashboard</Link>
          <Link href="/api/v1/auth/logout">Logout</Link>
        </nav>
      </aside>
      <main>
        <header
          style={{
            borderBottom: "1px solid var(--border)",
            padding: "0.75rem 1rem",
            color: "var(--text-muted)",
          }}
        >
          AI Review Dashboard
        </header>
        <QueryProvider>
          <div style={{ padding: "1rem" }}>{children}</div>
        </QueryProvider>
      </main>
    </div>
  );
}
