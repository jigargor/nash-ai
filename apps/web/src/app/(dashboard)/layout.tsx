import Link from "next/link";

import { QueryProvider } from "@/components/providers/query-provider";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const prDetailHref = "/repos/acme/repo/prs/1";
  // #region agent log
  fetch("http://127.0.0.1:7582/ingest/e6a057ab-47e4-4505-9884-d384fd412c69",{method:"POST",headers:{"Content-Type":"application/json","X-Debug-Session-Id":"7b2718"},body:JSON.stringify({sessionId:"7b2718",runId:"pre-fix-1",hypothesisId:"H1",location:"app/(dashboard)/layout.tsx:8",message:"sidebar_pr_detail_link_rendered",data:{href:prDetailHref},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
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
          <Link href={prDetailHref}>PR Detail</Link>
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
