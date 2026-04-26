"use client";

import type { Finding } from "@ai-code-review/shared-types";
import { useEffect } from "react";

import { DiffViewer } from "@/components/review/diff-viewer";
import { FileTree } from "@/components/review/file-tree";
import { FindingsPanel } from "@/components/review/findings-panel";
import { ReviewTimeline } from "@/components/review/review-timeline";
import { StreamingStatus } from "@/components/review/streaming-status";
import { useDismissFinding, useRerunReview } from "@/hooks/use-review-actions";
import { useReview } from "@/hooks/use-review";
import { useReviewStream } from "@/hooks/use-review-stream";
import { useReviewUiStore } from "@/stores/review-ui-store";

interface PrReviewPageClientProps {
  owner: string;
  repo: string;
  prNumber: string;
  reviewId: number;
  installationId: number;
}

function isFindingVisible(_finding: Finding): boolean {
  return true;
}

export function PrReviewPageClient({ owner, repo, prNumber, reviewId, installationId }: PrReviewPageClientProps) {
  const reviewQuery = useReview(reviewId, installationId);
  const rerunMutation = useRerunReview();
  const dismissMutation = useDismissFinding();
  const selectedFindingIndex = useReviewUiStore((state) => state.selectedFindingIndex);
  const setSelectedFindingIndex = useReviewUiStore((state) => state.setSelectedFindingIndex);
  const { events, connectionState } = useReviewStream(reviewId, installationId);

  const findings = reviewQuery.data?.findings?.findings?.filter(isFindingVisible) ?? [];
  const summary = reviewQuery.data?.findings?.summary ?? "";
  const findingOutcomes = reviewQuery.data?.finding_outcomes ?? [];
  const isFailedReview = reviewQuery.data?.status === "failed";

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!["j", "k"].includes(event.key)) return;
      if (!findings.length) return;
      event.preventDefault();
      const current = selectedFindingIndex ?? 0;
      if (event.key === "j") setSelectedFindingIndex(Math.min(current + 1, findings.length - 1));
      if (event.key === "k") setSelectedFindingIndex(Math.max(current - 1, 0));
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [findings.length, selectedFindingIndex, setSelectedFindingIndex]);

  if (reviewQuery.isLoading)
    return <section style={{ padding: "1rem" }}>Loading review details and findings panels...</section>;

  if (reviewQuery.isError)
    return (
      <section style={{ padding: "1rem" }}>
        <h1>API unreachable</h1>
        <p style={{ color: "var(--text-muted)" }}>Could not load review data. Retry in a moment.</p>
      </section>
    );

  if (!reviewQuery.data)
    return (
      <section style={{ padding: "1rem" }}>
        <h1>Review not found</h1>
      </section>
    );

  if (!findings.length)
    return (
      <section style={{ padding: "1rem" }}>
        <h1>
          {owner}/{repo} · PR #{prNumber}
        </h1>
        <p style={{ color: "var(--text-muted)" }}>
          {reviewQuery.data.status === "running"
            ? "Review still running..."
            : isFailedReview
              ? "Review failed before findings were produced."
              : "No findings for this review."}
        </p>
        {isFailedReview ? (
          <button
            type="button"
            disabled={rerunMutation.isPending}
            onClick={() => rerunMutation.mutate({ reviewId, installationId })}
            style={{
              border: "1px solid var(--border)",
              borderRadius: "0.5rem",
              background: "transparent",
              color: "inherit",
              cursor: rerunMutation.isPending ? "wait" : "pointer",
              padding: "0.35rem 0.8rem",
            }}
          >
            {rerunMutation.isPending ? "Retrying..." : "Retry review"}
          </button>
        ) : null}
      </section>
    );

  function handleCopySuggestion(index: number): void {
    const suggestion = findings[index]?.suggestion;
    if (!suggestion) return;
    void navigator.clipboard.writeText(suggestion);
  }

  function handleDismiss(index: number): void {
    void dismissMutation.mutateAsync({ reviewId, findingIndex: index, installationId });
  }

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      <header
        style={{
          border: "1px solid var(--border)",
          borderRadius: "0.75rem",
          background: "var(--card)",
          padding: "0.75rem",
        }}
      >
        <h1 style={{ margin: 0, fontFamily: "var(--font-instrument-serif)" }}>
          {owner}/{repo} · PR #{prNumber}
        </h1>
        <p style={{ marginBottom: "0.25rem", color: "var(--text-muted)" }}>{summary}</p>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <StreamingStatus state={connectionState} />
          <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
            {reviewQuery.data.tokens_used ?? 0} tokens · ${reviewQuery.data.cost_usd ?? "0.000000"}
          </div>
        </div>
        <button
          type="button"
          onClick={() => rerunMutation.mutate({ reviewId, installationId })}
          style={{
            marginTop: "0.75rem",
            border: "1px solid var(--border)",
            borderRadius: "0.5rem",
            background: "transparent",
            color: "inherit",
            padding: "0.35rem 0.8rem",
          }}
        >
          {rerunMutation.isPending ? "Retrying..." : isFailedReview ? "Retry review" : "Re-run review"}
        </button>
      </header>

      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: "0.75rem",
          background: "var(--card)",
          display: "grid",
          gridTemplateColumns: "minmax(220px, 1fr) minmax(380px, 2fr) minmax(260px, 1fr)",
          minHeight: "60vh",
        }}
      >
        <FileTree findings={findings} onSelectFinding={setSelectedFindingIndex} />
        <DiffViewer findings={findings} selectedFindingIndex={selectedFindingIndex} onSelectFinding={setSelectedFindingIndex} />
        <FindingsPanel
          findings={findings}
          findingOutcomes={findingOutcomes}
          selectedFindingIndex={selectedFindingIndex}
          onSelectFinding={setSelectedFindingIndex}
          onDismiss={handleDismiss}
          onCopySuggestion={handleCopySuggestion}
        />
      </div>
      <ReviewTimeline events={events} />
    </section>
  );
}
