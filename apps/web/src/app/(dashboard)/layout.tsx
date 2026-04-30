import type { Metadata } from "next";

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { QueryProvider } from "@/components/providers/query-provider";
import { buildSeoMetadata } from "@/lib/seo";

export const metadata: Metadata = buildSeoMetadata({
  title: "Dashboard",
  description: "Authenticated Nash AI dashboard for repository and review operations.",
  path: "/dashboard",
  noindex: true,
});

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <QueryProvider>
      <DashboardShell>{children}</DashboardShell>
    </QueryProvider>
  );
}
