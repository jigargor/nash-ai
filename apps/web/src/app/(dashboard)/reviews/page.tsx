"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useInstallations } from "@/hooks/use-installations";
import { useReviews } from "@/hooks/use-reviews";

function statusVisualClass(status: string): string {
  if (status === "done") return "review-status-dot review-status-done";
  if (status === "failed") return "review-status-dot review-status-failed";
  return "review-status-dot review-status-running";
}

function statusAriaLabel(status: string): string {
  if (status === "done") return "Done";
  if (status === "failed") return "Failed";
  return "Running";
}

function modelLabel(provider?: string | null, model?: string | null): string {
  if (!provider && !model) return "—";
  return `${provider ?? "provider"} / ${model ?? "model"}`;
}

export default function ReviewsPage() {
  const installations = useInstallations();
  const [installationId, setInstallationId] = useState<number | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState("all");
  const [findingsFilter, setFindingsFilter] = useState<"all" | "zero" | "nonzero">("all");
  const reviewsQuery = useReviews(installationId);

  const allStatuses = useMemo(() => {
    const reviews = reviewsQuery.data ?? [];
    return [...new Set(reviews.map((item) => item.status))];
  }, [reviewsQuery.data]);

  const filteredReviews = useMemo(() => {
    const reviews = reviewsQuery.data ?? [];
    let list = reviews;
    if (statusFilter !== "all") {
      list = list.filter((item) => item.status === statusFilter);
    }
    if (findingsFilter === "zero") {
      list = list.filter((item) => (item.findings_count ?? 0) === 0);
    } else if (findingsFilter === "nonzero") {
      list = list.filter((item) => (item.findings_count ?? 0) > 0);
    }
    return list;
  }, [reviewsQuery.data, statusFilter, findingsFilter]);

  const installationOptions = installations.data ?? [];

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      <Panel>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
          <label htmlFor="installation-select" style={{ color: "var(--text-muted)" }}>
            Installation
          </label>
          <select
            id="installation-select"
            className="app-search"
            style={{ width: "260px" }}
            value={installationId ?? ""}
            onChange={(event) =>
              setInstallationId(event.target.value ? Number(event.target.value) : undefined)
            }
          >
            <option value="">All installations</option>
            {installationOptions.map((installation) => (
              <option key={installation.installation_id} value={installation.installation_id}>
                {installation.account_login} ({installation.installation_id})
              </option>
            ))}
          </select>

          <label htmlFor="status-filter" style={{ color: "var(--text-muted)" }}>
            Status
          </label>
          <select
            id="status-filter"
            className="app-search"
            style={{ width: "220px" }}
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="all">All statuses</option>
            {allStatuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>

          <label htmlFor="findings-filter" style={{ color: "var(--text-muted)" }}>
            Findings
          </label>
          <select
            id="findings-filter"
            className="app-search"
            style={{ width: "200px" }}
            value={findingsFilter}
            onChange={(event) => setFindingsFilter(event.target.value as "all" | "zero" | "nonzero")}
          >
            <option value="all">Any count</option>
            <option value="zero">0 findings</option>
            <option value="nonzero">1+ findings</option>
          </select>
        </div>
      </Panel>

      {reviewsQuery.isLoading ? (
        <StateBlock title="Loading reviews" description="Fetching the latest review runs." />
      ) : null}

      {reviewsQuery.isError ? (
        <StateBlock title="Could not load reviews" description="Please retry after the API is reachable." />
      ) : null}

      {!reviewsQuery.isLoading && !reviewsQuery.isError && filteredReviews.length === 0 ? (
        <StateBlock
          title="No reviews found"
          description="Try a different installation or relax status / findings filters."
        />
      ) : null}

      {!reviewsQuery.isLoading && !reviewsQuery.isError && filteredReviews.length > 0 ? (
        <Panel>
          <div className="reviews-list-grid">
            {filteredReviews.map((review) => (
              <Link
                key={review.id}
                href={`/repos/${review.repo_full_name}/prs/${review.pr_number}?reviewId=${review.id}&installationId=${review.installation_id}`}
                className="review-row-link"
              >
                <span className="review-row-left">
                  <span
                    className={statusVisualClass(review.status)}
                    aria-label={statusAriaLabel(review.status)}
                    title={statusAriaLabel(review.status)}
                  />
                  <span className="review-row-title">
                    {review.repo_full_name} · PR #{review.pr_number}
                  </span>
                </span>
                <span className="review-row-right">
                  <span className="review-findings-pill">{review.findings_count ?? 0} findings</span>
                  <span className="review-cost-text">${review.cost_usd ?? "0.000000"}</span>
                </span>
                <span className="review-hover-card" aria-hidden>
                  <span className="review-hover-row">
                    <span className="review-hover-key">Model</span>
                    <span className="review-hover-value">{modelLabel(review.model_provider, review.model)}</span>
                  </span>
                  <span className="review-hover-row">
                    <span className="review-hover-key">Tokens</span>
                    <span className="review-hover-value">{review.tokens_used ?? 0}</span>
                  </span>
                  <span className="review-hover-row">
                    <span className="review-hover-key">Files changed</span>
                    <span className="review-hover-value">
                      {typeof review.files_changed === "number" ? review.files_changed : "—"}
                    </span>
                  </span>
                  <span className="review-hover-row">
                    <span className="review-hover-key">LOC changed</span>
                    <span className="review-hover-value">
                      {typeof review.lines_changed === "number" ? review.lines_changed : "—"}
                    </span>
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </Panel>
      ) : null}
    </section>
  );
}
