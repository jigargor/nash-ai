"use client";

import type { Finding } from "@ai-code-review/shared-types";
import { useEffect } from "react";

import { DiffViewer } from "@/components/review/diff-viewer";
import { FileTree } from "@/components/review/file-tree";
import { FindingsPanel } from "@/components/review/findings-panel";
import { ReviewTimeline } from "@/components/review/review-timeline";
import { StreamingStatus } from "@/components/review/streaming-status";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import { useReviewModelAudits } from "@/hooks/use-review-model-audits";
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
  const modelAudits = useReviewModelAudits(reviewId, installationId);
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

  if (reviewQuery.isLoading) {
    return <StateBlock title="Loading review details" description="Preparing findings, stream status, and timeline." />;
  }

  if (reviewQuery.isError) {
    return (
      <StateBlock title="API unreachable" description="Could not load review data. Retry in a moment." />
    );
  }

  if (!reviewQuery.data) {
    return (
      <StateBlock title="Review not found" description="The requested review is no longer available." />
    );
  }

  if (!findings.length) {
    return (
      <Panel elevated>
        <h1 style={{ marginTop: 0, fontFamily: "var(--font-instrument-serif)" }}>
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
          <Button
            variant="ghost"
            disabled={rerunMutation.isPending}
            onClick={() => rerunMutation.mutate({ reviewId, installationId })}
          >
            {rerunMutation.isPending ? "Retrying..." : "Retry review"}
          </Button>
        ) : null}
      </Panel>
    );
  }

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
      <Panel elevated>
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
        <p style={{ color: "var(--text-muted)", marginBottom: 0, marginTop: "0.45rem", fontSize: "0.85rem" }}>
          Model: {reviewQuery.data.model_provider ?? "provider"} / {reviewQuery.data.model}
          {modelAudits.data ? ` · audit stages: ${modelAudits.data.model_audits.length}` : ""}
        </p>
        <Button
          variant={isFailedReview ? "danger" : "ghost"}
          onClick={() => rerunMutation.mutate({ reviewId, installationId })}
          style={{ marginTop: "0.75rem" }}
        >
          {rerunMutation.isPending ? "Retrying..." : isFailedReview ? "Retry review" : "Re-run review"}
        </Button>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) minmax(380px, 2fr) minmax(260px, 1fr)", minHeight: "60vh" }} className="panel panel-elevated">
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
