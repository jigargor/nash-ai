"use client";

import { useReviews } from "@/hooks/use-reviews";

export default function DashboardHomePage() {
  const reviews = useReviews();
  const totalTokens = (reviews.data ?? []).reduce((sum, review) => sum + (review.tokens_used ?? 0), 0);
  const totalCost = (reviews.data ?? []).reduce((sum, review) => sum + Number(review.cost_usd ?? 0), 0);

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: "0.75rem",
        background: "var(--card)",
        padding: "1rem",
      }}
    >
      <h1 style={{ marginTop: 0, fontFamily: "var(--font-instrument-serif)" }}>Dashboard</h1>
      {reviews.isLoading ? <p style={{ color: "var(--text-muted)" }}>Loading recent reviews...</p> : null}
      {reviews.isError ? <p style={{ color: "var(--severity-critical)" }}>Failed to load reviews.</p> : null}
      {!reviews.isLoading && !reviews.isError && (reviews.data?.length ?? 0) === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No installations connected yet.</p>
      ) : null}
      {reviews.data?.map((review) => (
        <article
          key={review.id}
          style={{
            border: "1px solid var(--border)",
            borderRadius: "0.5rem",
            padding: "0.5rem",
            marginBottom: "0.5rem",
          }}
        >
          <a href={`/repos/${review.repo_full_name}/prs/${review.pr_number}?reviewId=${review.id}`}>
            {review.repo_full_name} · PR #{review.pr_number}
          </a>
          <div style={{ color: "var(--text-muted)" }}>
            {review.status} · {review.tokens_used ?? 0} tokens
          </div>
        </article>
      ))}
      <div style={{ color: "var(--text-muted)", marginBottom: "0.5rem" }}>
        Reviews this month: {reviews.data?.length ?? 0} · tokens: {totalTokens} · cost: ${totalCost.toFixed(6)}
      </div>
      <a href="https://github.com/settings/apps" target="_blank" rel="noreferrer">
        Install GitHub App
      </a>
    </section>
  );
}
