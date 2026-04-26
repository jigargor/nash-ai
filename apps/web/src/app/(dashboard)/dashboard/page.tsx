"use client";

import { useOutcomeSummary } from "@/hooks/use-outcome-summary";
import { useInstallations } from "@/hooks/use-installations";
import { useReviews } from "@/hooks/use-reviews";

export default function DashboardHomePage() {
  const installations = useInstallations();
  const activeInstallations = installations.data?.filter((installation) => installation.active) ?? [];
  const installationId = activeInstallations[0]?.installation_id;
  const reviews = useReviews(installationId);
  const outcomeSummary = useOutcomeSummary(installationId);
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
      {installations.isLoading || reviews.isLoading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading recent reviews...</p>
      ) : null}
      {installations.isError || reviews.isError ? (
        <p style={{ color: "var(--severity-critical)" }}>Failed to load reviews.</p>
      ) : null}
      {!installations.isLoading && !installations.isError && !installationId ? (
        <p style={{ color: "var(--text-muted)" }}>No installations connected yet.</p>
      ) : null}
      {!reviews.isLoading && !reviews.isError && installationId && (reviews.data?.length ?? 0) === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No reviews yet for this installation.</p>
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
          <a href={`/repos/${review.repo_full_name}/prs/${review.pr_number}?reviewId=${review.id}&installationId=${review.installation_id}`}>
            {review.repo_full_name} PR #{review.pr_number}
          </a>
          <div style={{ color: "var(--text-muted)" }}>
            {review.status} / {review.tokens_used ?? 0} tokens
          </div>
        </article>
      ))}
      <div style={{ color: "var(--text-muted)", marginBottom: "0.5rem" }}>
        Reviews this month: {reviews.data?.length ?? 0} / tokens: {totalTokens} / cost: ${totalCost.toFixed(6)}
      </div>
      <div style={{ color: "var(--text-muted)", marginBottom: "0.5rem" }}>
        Useful rate:{" "}
        {outcomeSummary.data
          ? `${(outcomeSummary.data.global_metrics.useful_rate * 100).toFixed(1)}%`
          : "N/A"}{" "}
        / applied:{" "}
        {outcomeSummary.data
          ? `${(outcomeSummary.data.global_metrics.applied_rate * 100).toFixed(1)}%`
          : "N/A"}{" "}
        / dismissed:{" "}
        {outcomeSummary.data
          ? `${(outcomeSummary.data.global_metrics.dismiss_rate * 100).toFixed(1)}%`
          : "N/A"}
      </div>
      {activeInstallations.length > 0 ? (
        <div style={{ color: "var(--text-muted)" }}>
          GitHub App installed for {activeInstallations.map((installation) => installation.account_login).join(", ")}
        </div>
      ) : (
        <a href="https://github.com/settings/apps" target="_blank" rel="noreferrer">
          Install GitHub App
        </a>
      )}
    </section>
  );
}
