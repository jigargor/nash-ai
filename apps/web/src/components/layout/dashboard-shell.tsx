"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent, type PropsWithChildren } from "react";

import { TermsAcceptanceModal } from "@/components/layout/terms-acceptance-modal";
import { useDashboardSearch } from "@/hooks/use-dashboard-search";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useInstallations } from "@/hooks/use-installations";
import { useAcceptTerms, useTermsStatus } from "@/hooks/use-terms-status";

interface NavItem {
  label: string;
  href: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "All Reviews", href: "/reviews" },
  { label: "Repositories", href: "/repos" },
  { label: "Models", href: "/models" },
  { label: "Code Tour", href: "/code-tour" },
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
  if (pathname.startsWith("/code-tour")) return "Code Tour";
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
  if (href === "/code-tour") {
    return pathname === "/code-tour" || pathname.startsWith("/code-tour/");
  }
  if (href === "/settings") return pathname === "/settings" || pathname.startsWith("/settings/");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function DashboardShell({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const router = useRouter();
  const currentUser = useCurrentUser();
  const installations = useInstallations();
  const [searchInput, setSearchInput] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const searchQuery = useMemo(() => searchInput.trim(), [searchInput]);
  const searchResults = useDashboardSearch(searchQuery);
  const activeInstallations = installations.data?.filter((item) => item.active).length ?? 0;
  const termsStatus = useTermsStatus();
  const acceptTerms = useAcceptTerms();
  const requiresTermsAcceptance =
    termsStatus.data?.requires_terms_acceptance === true && currentUser.data?.authenticated === true;

  function handleSearchSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const normalized = searchInput.trim();
    if (!normalized) return;
    setIsSearchOpen(false);
    router.push(`/reviews?q=${encodeURIComponent(normalized)}`);
  }

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
              <form className="app-search-wrap" onSubmit={handleSearchSubmit}>
                <input
                  type="search"
                  className="app-search"
                  placeholder="Search PRs, repos, issues"
                  value={searchInput}
                  onChange={(event) => {
                    setSearchInput(event.target.value);
                    setIsSearchOpen(true);
                  }}
                  onFocus={() => setIsSearchOpen(true)}
                />
                {isSearchOpen && searchQuery.length >= 2 ? (
                  <div className="app-search-results" role="listbox" aria-label="Search results">
                    {searchResults.isLoading ? (
                      <span className="app-search-result-empty">Searching…</span>
                    ) : searchResults.data && searchResults.data.length > 0 ? (
                      searchResults.data.map((item) =>
                        item.href.startsWith("http") ? (
                          <a
                            key={`${item.type}:${item.href}`}
                            href={item.href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="app-search-result-row"
                            onClick={() => setIsSearchOpen(false)}
                          >
                            <span>{item.label}</span>
                            {item.subtitle ? <small>{item.subtitle}</small> : null}
                          </a>
                        ) : (
                          <Link
                            key={`${item.type}:${item.href}`}
                            href={item.href}
                            className="app-search-result-row"
                            onClick={() => setIsSearchOpen(false)}
                          >
                            <span>{item.label}</span>
                            {item.subtitle ? <small>{item.subtitle}</small> : null}
                          </Link>
                        ),
                      )
                    ) : (
                      <span className="app-search-result-empty">No matches found.</span>
                    )}
                  </div>
                ) : null}
              </form>
            </div>
          </div>
        </header>

        <div className="app-content">{children}</div>
      </main>
      {requiresTermsAcceptance ? (
        <TermsAcceptanceModal
          isSubmitting={acceptTerms.isPending}
          onAccept={() => {
            void acceptTerms.mutateAsync();
          }}
        />
      ) : null}
    </div>
  );
}
