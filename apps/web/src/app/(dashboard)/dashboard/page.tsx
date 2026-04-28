"use client";

import Link from "next/link";

import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { Button } from "@/components/ui/button";
import { useUsageSummary } from "@/hooks/use-usage-summary";
import { useOutcomeSummary } from "@/hooks/use-outcome-summary";
import { useInstallations } from "@/hooks/use-installations";
import { useRerunReview } from "@/hooks/use-review-actions";
import { useReviews } from "@/hooks/use-reviews";
import { isReviewInFlightStatus } from "@/lib/review-status";

export default function DashboardHomePage() {
  const installations = useInstallations();
  const activeInstallations = installations.data?.filter((installation) => installation.active) ?? [];
  const installationId = activeInstallations[0]?.installation_id;
  const reviews = useReviews(installationId);
  const usageSummary = useUsageSummary(installationId);
  const outcomeSummary = useOutcomeSummary(installationId);
  const retryReview = useRerunReview();
  const totalTokens = (reviews.data ?? []).reduce((sum, review) => sum + (review.tokens_used ?? 0), 0);
  const totalCost = (reviews.data ?? []).reduce((sum, review) => sum + Number(review.cost_usd ?? 0), 0);
  const dailyUsageRequests = usageSummary.data?.daily_requests.at(-1)?.requests ?? 0;
  const weeklyUsageRequests = usageSummary.data?.weekly_requests.at(-1)?.requests ?? 0;
  const capState = usageSummary.data?.session_cap.state ?? "safe";
  const capLabel =
    capState === "capped" ? "Cap reached" : capState === "near-cap" ? "Near cap" : "Within cap";

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      <div className="metrics-grid">
        <article className="metric-card">
          <p className="metric-label">Reviews this month</p>
          <p className="metric-value">{reviews.data?.length ?? 0}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Tokens processed</p>
          <p className="metric-value">{totalTokens}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Estimated cost</p>
          <p className="metric-value">${totalCost.toFixed(6)}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Service requests (24h)</p>
          <p className="metric-value">{dailyUsageRequests}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Service requests (7d)</p>
          <p className="metric-value">{weeklyUsageRequests}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Session cap</p>
          <p className="metric-value">{capLabel}</p>
        </article>
      </div>

      <Panel elevated>
        <h1 style={{ marginTop: 0, marginBottom: "0.4rem", fontFamily: "var(--font-instrument-serif)" }}>Recent Reviews</h1>
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          Active installations: {activeInstallations.length} · useful rate{" "}
          {outcomeSummary.data ? `${(outcomeSummary.data.global_metrics.useful_rate * 100).toFixed(1)}%` : "N/A"}
        </p>

        {installations.isLoading || reviews.isLoading ? (
          <StateBlock title="Loading reviews" description="Syncing recent review activity." />
        ) : null}

        {installations.isError || reviews.isError ? (
          <StateBlock title="Failed to load reviews" description="Retry once the API becomes available." />
        ) : null}

        {!installations.isLoading && !installations.isError && !installationId ? (
          <StateBlock
            title="No installations connected"
            description="Install the GitHub App to start receiving review activity."
            action={
              <a className="button button-primary" href="https://github.com/settings/apps" target="_blank" rel="noreferrer">
                Install GitHub App
              </a>
            }
          />
        ) : null}

        {!reviews.isLoading && !reviews.isError && installationId && (reviews.data?.length ?? 0) === 0 ? (
          <StateBlock
            title="No reviews yet"
            description="Open or synchronize a pull request to trigger the first run."
          />
        ) : null}

        {!reviews.isLoading && !reviews.isError ? (
          <div style={{ display: "grid", gap: "0.55rem" }}>
            {reviews.data?.map((review) => (
              <article
                key={review.id}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-md)",
                  padding: "0.65rem 0.8rem",
                  display: "grid",
                  gap: "0.35rem",
                }}
              >
                <Link href={`/repos/${review.repo_full_name}/prs/${review.pr_number}?reviewId=${review.id}&installationId=${review.installation_id}`}>
                  {review.repo_full_name} · PR #{review.pr_number}
                </Link>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", color: "var(--text-muted)" }}>
                  <span>
                    {isReviewInFlightStatus(review.status) ? "● " : ""}
                    {review.status}
                    {isReviewInFlightStatus(review.status) ? " (refreshing…)" : ""} · {review.tokens_used ?? 0} tokens · $
                    {review.cost_usd ?? "0.000000"}
                  </span>
                  {review.status === "failed" ? (
                    <Button
                      variant="ghost"
                      disabled={retryReview.isPending && retryReview.variables?.reviewId === review.id}
                      onClick={() =>
                        retryReview.mutate({
                          reviewId: review.id,
                          installationId: review.installation_id,
                        })
                      }
                    >
                      {retryReview.isPending && retryReview.variables?.reviewId === review.id ? "Queuing…" : "Retry"}
                    </Button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </Panel>

      <Panel>
        <h2 style={{ marginTop: 0, marginBottom: "0.45rem" }}>Evaluate External</h2>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          Run critical-only analysis on a public GitHub repository with cost controls and staged execution.
        </p>
        <div style={{ marginTop: "0.75rem" }}>
          <Link href="/evaluate-external" className="button button-primary">
            Open Evaluate External
          </Link>
        </div>
      </Panel>
    </section>
  );
}
