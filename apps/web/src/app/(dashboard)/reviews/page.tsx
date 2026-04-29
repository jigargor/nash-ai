"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useInstallations } from "@/hooks/use-installations";
import { useReviews } from "@/hooks/use-reviews";
import type { ReviewListFilters } from "@/lib/api/reviews";

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

function isPositiveNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && value > 0;
}

function formatReviewInstant(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function localInputToIsoEndOfDay(dateOnly: string): string | undefined {
  if (!dateOnly.trim()) return undefined;
  const d = new Date(`${dateOnly}T23:59:59`);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString();
}

function localInputToIsoStartOfDay(dateOnly: string): string | undefined {
  if (!dateOnly.trim()) return undefined;
  const d = new Date(`${dateOnly}T00:00:00`);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString();
}

export default function ReviewsPage() {
  const installations = useInstallations();
  const [installationId, setInstallationId] = useState<number | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState("all");
  const [findingsFilter, setFindingsFilter] = useState<"all" | "zero" | "nonzero">("all");
  const [createdOnOrAfter, setCreatedOnOrAfter] = useState("");
  const [createdOnOrBefore, setCreatedOnOrBefore] = useState("");

  const reviewDateFilters = useMemo((): ReviewListFilters | undefined => {
    const filters: ReviewListFilters = {};
    const afterIso = localInputToIsoStartOfDay(createdOnOrAfter);
    const beforeIso = localInputToIsoEndOfDay(createdOnOrBefore);
    if (afterIso) filters.createdAfter = afterIso;
    if (beforeIso) filters.createdBefore = beforeIso;
    if (!filters.createdAfter && !filters.createdBefore) return undefined;
    return filters;
  }, [createdOnOrAfter, createdOnOrBefore]);

  const reviewsQuery = useReviews(installationId, reviewDateFilters);

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

          <label htmlFor="created-after" style={{ color: "var(--text-muted)" }}>
            Started on or after
          </label>
          <input
            id="created-after"
            type="date"
            className="app-search"
            style={{ width: "160px" }}
            value={createdOnOrAfter}
            onChange={(event) => setCreatedOnOrAfter(event.target.value)}
          />

          <label htmlFor="created-before" style={{ color: "var(--text-muted)" }}>
            Started on or before
          </label>
          <input
            id="created-before"
            type="date"
            className="app-search"
            style={{ width: "160px" }}
            value={createdOnOrBefore}
            onChange={(event) => setCreatedOnOrBefore(event.target.value)}
          />
        </div>
        <p style={{ margin: "0.35rem 0 0", fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Date filters use your local calendar day converted to UTC bounds (start 00:00 / end 23:59:59) for the API{" "}
          <code>created_after</code> / <code>created_before</code> query.
        </p>
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
                  <span className="review-cost-text" style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                    {formatReviewInstant(review.created_at)}
                  </span>
                  <span className="review-findings-pill">{review.findings_count ?? 0} findings</span>
                  <span className="review-cost-text">${review.cost_usd ?? "0.000000"}</span>
                </span>
                <span className="review-hover-card" aria-hidden>
                  <span className="review-hover-row">
                    <span className="review-hover-key">Model</span>
                    <span className="review-hover-value">{modelLabel(review.model_provider, review.model)}</span>
                  </span>
                  {isPositiveNumber(review.tokens_used) ? (
                    <span className="review-hover-row">
                      <span className="review-hover-key">Tokens</span>
                      <span className="review-hover-value">{review.tokens_used}</span>
                    </span>
                  ) : null}
                  {isPositiveNumber(review.files_changed) ? (
                    <span className="review-hover-row">
                      <span className="review-hover-key">Files changed</span>
                      <span className="review-hover-value">{review.files_changed}</span>
                    </span>
                  ) : null}
                  {isPositiveNumber(review.lines_changed) ? (
                    <span className="review-hover-row">
                      <span className="review-hover-key">LOC changed</span>
                      <span className="review-hover-value">{review.lines_changed}</span>
                    </span>
                  ) : null}
                </span>
              </Link>
            ))}
          </div>
        </Panel>
      ) : null}
    </section>
  );
}
