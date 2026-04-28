"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { PropsWithChildren } from "react";

import { useCurrentUser } from "@/hooks/use-current-user";
import { useInstallations } from "@/hooks/use-installations";

interface NavItem {
  label: string;
  href: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "All Reviews", href: "/reviews" },
  { label: "Repositories", href: "/repos" },
  { label: "Models", href: "/models" },
  { label: "Evaluate External", href: "/evaluate-external" },
  { label: "Settings", href: "/settings" },
];

function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

/** Single PR review view lives under /repos/:owner/:repo/prs/:number — treat as part of All Reviews, not Repositories. */
function isPullRequestReviewRoute(pathname: string): boolean {
  return /^\/repos\/[^/]+\/[^/]+\/prs\/[^/]+$/.test(pathname);
}

function pageTitle(pathname: string): string {
  if (pathname.startsWith("/reviews")) return "All Reviews";
  if (isPullRequestReviewRoute(pathname)) return "All Reviews";
  if (pathname.startsWith("/repos")) return "Repositories";
  if (pathname.startsWith("/models")) return "Models";
  if (pathname.startsWith("/evaluate-external")) return "Evaluate External";
  if (pathname.startsWith("/settings")) return "Settings";
  return "Dashboard";
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/dashboard";
  if (href === "/reviews") {
    return pathname === "/reviews" || pathname.startsWith("/reviews/") || isPullRequestReviewRoute(pathname);
  }
  if (href === "/repos") {
    if (isPullRequestReviewRoute(pathname)) return false;
    return pathname === "/repos" || pathname.startsWith("/repos/");
  }
  if (href === "/models") return pathname === "/models" || pathname.startsWith("/models/");
  if (href === "/evaluate-external") {
    return pathname === "/evaluate-external" || pathname.startsWith("/evaluate-external/");
  }
  if (href === "/settings") return pathname === "/settings" || pathname.startsWith("/settings/");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function DashboardShell({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const currentUser = useCurrentUser();
  const installations = useInstallations();
  const activeInstallations = installations.data?.filter((item) => item.active).length ?? 0;

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div>
          <h1 className="app-brand">Nash AI</h1>
          <p className="app-topbar-subtitle" style={{ marginTop: "0.25rem" }}>
            AI review control center
          </p>
        </div>

        <nav className="app-sidebar-nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={classNames("app-sidebar-link", isActive(pathname, item.href) && "app-sidebar-link-active")}
            >
              <span>{item.label}</span>
            </Link>
          ))}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- session cookie clear via API */}
          <a href="/api/v1/auth/logout" className="app-sidebar-link">
            <span>Logout</span>
          </a>
        </nav>

        <section className="sidebar-foot">
          <div style={{ display: "grid", gap: "0.4rem" }}>
            <span className="status-pill">Installations: {activeInstallations}</span>
            <span className="status-pill">
              Agent: {activeInstallations > 0 ? "Connected" : "Action required"}
            </span>
            <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
              {currentUser.data?.authenticated ? `Signed in as @${currentUser.data.user?.login ?? "user"}` : "Signed in"}
            </span>
          </div>
        </section>
      </aside>

      <main className="app-main">
        <header className="app-topbar">
          <div className="app-topbar-row">
            <div>
              <h2 className="app-topbar-title">{pageTitle(pathname)}</h2>
              <p className="app-topbar-subtitle">Track usage, findings, and external evaluation risk.</p>
            </div>
            <div className="app-topbar-actions">
              <input
                className="app-search"
                type="search"
                disabled
                aria-label="Search (coming soon)"
                placeholder="Search PRs, repos, issues (coming soon)"
              />
            </div>
          </div>
        </header>

        <div className="app-content">{children}</div>
      </main>
    </div>
  );
}
