"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useInstallations } from "@/hooks/use-installations";
import { useReviews } from "@/hooks/use-reviews";
import { isReviewInFlightStatus } from "@/lib/review-status";

export default function ReviewsPage() {
  const installations = useInstallations();
  const [installationId, setInstallationId] = useState<number | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState("all");
  const reviewsQuery = useReviews(installationId);

  const allStatuses = useMemo(() => {
    const reviews = reviewsQuery.data ?? [];
    return [...new Set(reviews.map((item) => item.status))];
  }, [reviewsQuery.data]);

  const filteredReviews = useMemo(() => {
    const reviews = reviewsQuery.data ?? [];
    if (statusFilter === "all") return reviews;
    return reviews.filter((item) => item.status === statusFilter);
  }, [reviewsQuery.data, statusFilter]);

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
        </div>
      </Panel>

      {reviewsQuery.isLoading ? (
        <StateBlock title="Loading reviews" description="Fetching the latest review runs." />
      ) : null}

      {reviewsQuery.isError ? (
        <StateBlock title="Could not load reviews" description="Please retry after the API is reachable." />
      ) : null}

      {!reviewsQuery.isLoading && !reviewsQuery.isError && filteredReviews.length === 0 ? (
        <StateBlock title="No reviews found" description="Try a different installation or clear status filters." />
      ) : null}

      {!reviewsQuery.isLoading && !reviewsQuery.isError && filteredReviews.length > 0 ? (
        <Panel>
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {filteredReviews.map((review) => (
              <Link
                key={review.id}
                href={`/repos/${review.repo_full_name}/prs/${review.pr_number}?reviewId=${review.id}&installationId=${review.installation_id}`}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-md)",
                  padding: "0.65rem 0.8rem",
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "0.75rem",
                }}
              >
                <span>
                  {review.repo_full_name} · PR #{review.pr_number}
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  {isReviewInFlightStatus(review.status) ? "● " : ""}
                  {review.status}
                  {isReviewInFlightStatus(review.status) ? " (refreshing…)" : ""}
                  {review.model_provider || review.model ? ` · ${review.model_provider ?? "provider"}/${review.model ?? "model"}` : ""}
                  {" · "}
                  {review.tokens_used ?? 0} tokens · ${review.cost_usd ?? "0.000000"}
                </span>
              </Link>
            ))}
          </div>
        </Panel>
      ) : null}
    </section>
  );
}
