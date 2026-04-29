"use client";

import type { Finding } from "@ai-code-review/shared-types";
import Link from "next/link";
import { useCallback, useEffect, useMemo } from "react";

import { ActionChain } from "@/components/review/action-chain";
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
import { buildPrReviewDebugExport } from "@/lib/pr-review-debug-export";
import { isReviewInFlightStatus } from "@/lib/review-status";
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

function noFindingsBodyText(
  summary: string,
  debugArtifacts: Record<string, unknown> | null | undefined,
  isFailedReview: boolean,
  isInFlight: boolean,
): string {
  const trimmed = summary.trim();
  if (trimmed.length > 0) return trimmed;
  const fp = debugArtifacts?.fast_path_decision;
  if (fp && typeof fp === "object" && fp !== null && "reason" in fp) {
    const reason = (fp as Record<string, unknown>).reason;
    if (typeof reason === "string" && reason.trim().length > 0) return reason;
  }
  if (isFailedReview) return "Review failed before findings were produced.";
  if (isInFlight) return "Review is queued or running. This page refreshes every few seconds.";
  return "No issues matched the review thresholds, or findings were filtered before posting.";
}

function ReviewInProgressBanner(props: { reviewStatus: string; hasStaleFindings: boolean }) {
  const { reviewStatus, hasStaleFindings } = props;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        border: "1px solid var(--accent-muted)",
        background: "var(--card-muted)",
        borderRadius: "var(--radius-md)",
        padding: "0.85rem 1rem",
      }}
    >
      <p style={{ margin: 0, fontWeight: 600, color: "var(--text-primary)" }}>Review in progress</p>
      <p style={{ margin: "0.35rem 0 0", color: "var(--text-muted)", fontSize: "0.9rem" }}>
        Status: <strong style={{ color: "var(--accent)" }}>{reviewStatus || "starting"}</strong>
        {hasStaleFindings
          ? " · Findings below are from the last completed run until this one finishes."
          : " · This page checks for completion every few seconds."}
      </p>
    </div>
  );
}

export function PrReviewPageClient({ owner, repo, prNumber, reviewId, installationId }: PrReviewPageClientProps) {
  const reviewQuery = useReview(reviewId, installationId);
  const rerunMutation = useRerunReview();
  const dismissMutation = useDismissFinding();
  const modelAudits = useReviewModelAudits(reviewId, installationId);
  const selectedFindingIndex = useReviewUiStore((state) => state.selectedFindingIndex);
  const setSelectedFindingIndex = useReviewUiStore((state) => state.setSelectedFindingIndex);
  const { events, connectionState } = useReviewStream(reviewId, installationId);

  const reviewStatus = reviewQuery.data?.status ?? "";
  const isInFlight = isReviewInFlightStatus(reviewStatus) || rerunMutation.isPending;
  const findings = reviewQuery.data?.findings?.findings?.filter(isFindingVisible) ?? [];
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

  const audits = useMemo(() => modelAudits.data?.model_audits ?? [], [modelAudits.data]);
  const pipelineStagedFindingsPeak = useMemo(
    () =>
      audits.reduce((max, a) => (typeof a.findings_count === "number" ? Math.max(max, a.findings_count) : max), 0),
    [audits],
  );
  const postedFindingsCount = findings.length;
  const findingsStatusLabel =
    pipelineStagedFindingsPeak > postedFindingsCount
      ? `${postedFindingsCount} posted · ${pipelineStagedFindingsPeak} pipeline`
      : `${postedFindingsCount} findings`;

  const summaryParagraph = useMemo(() => {
    const row = reviewQuery.data;
    if (!row) return "";
    const visible = row.findings?.findings?.filter(isFindingVisible) ?? [];
    const sum = row.findings?.summary ?? "";
    if (visible.length) return sum;
    return noFindingsBodyText(
      sum,
      row.debug_artifacts,
      row.status === "failed",
      isReviewInFlightStatus(row.status) || rerunMutation.isPending,
    );
  }, [reviewQuery.data, rerunMutation.isPending]);

  const getDebugExportPayload = useCallback(() => {
    const row = reviewQuery.data;
    if (!row) {
      return { exported_at: new Date().toISOString(), error: "review_not_loaded" } as Record<string, unknown>;
    }
    const postedFindings = row.findings?.findings?.filter(isFindingVisible) ?? [];
    const modelAuditsList = modelAudits.data?.model_audits ?? [];
    const peak = modelAuditsList.reduce(
      (max, a) => (typeof a.findings_count === "number" ? Math.max(max, a.findings_count) : max),
      0,
    );
    return buildPrReviewDebugExport({
      exportedAtIso: new Date().toISOString(),
      reviewId,
      owner,
      repo,
      prNumber,
      status: row.status,
      summaryParagraph,
      model: row.model,
      modelProvider: row.model_provider ?? undefined,
      tokensUsed: row.tokens_used,
      costUsd: row.cost_usd,
      postedFindingsCount: postedFindings.length,
      pipelineStagedFindingsPeak: peak,
      postedFindings,
      findingOutcomes: row.finding_outcomes ?? [],
      modelAudits: modelAuditsList,
      debugArtifacts: row.debug_artifacts ?? null,
    });
  }, [
    reviewId,
    owner,
    repo,
    prNumber,
    reviewQuery.data,
    modelAudits.data,
    summaryParagraph,
  ]);

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

  const data = reviewQuery.data;
  const pipelineEmptyHint = modelAudits.isLoading
    ? "Loading pipeline stages…"
    : modelAudits.isError
      ? "Could not load model audits."
      : null;

  function handleCopySuggestion(index: number): void {
    const suggestion = findings[index]?.suggestion;
    if (!suggestion) return;
    void navigator.clipboard.writeText(suggestion);
  }

  function handleDismiss(index: number): void {
    void dismissMutation.mutateAsync({ reviewId, findingIndex: index, installationId });
  }

  return (
    <section className="pr-review-page" style={{ display: "grid", gap: "1rem" }}>
      <div style={{ marginBottom: "-0.35rem" }}>
        <Link
          href="/reviews"
          className="pr-review-back-link"
          aria-label="Back to all reviews"
        >
          <span aria-hidden className="pr-review-back-arrow">
            ←
          </span>
          Back to reviews
        </Link>
      </div>
      {isInFlight ? (
        <ReviewInProgressBanner reviewStatus={reviewStatus} hasStaleFindings={postedFindingsCount > 0} />
      ) : null}
      <Panel elevated>
        <h1 style={{ margin: 0, fontFamily: "var(--font-instrument-serif)", overflowWrap: "anywhere", wordBreak: "break-word" }}>
          {owner}/{repo} · PR #{prNumber}
        </h1>
        <p className="pr-review-summary-text" style={{ marginBottom: "0.25rem", color: "var(--text-muted)" }}>
          {summaryParagraph}
        </p>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
          <StreamingStatus state={connectionState} />
          <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
            {data.tokens_used ?? 0} tokens · ${data.cost_usd ?? "0.000000"} · {findingsStatusLabel}
          </div>
        </div>
        <p style={{ color: "var(--text-muted)", marginBottom: 0, marginTop: "0.45rem", fontSize: "0.85rem" }}>
          Model: {data.model_provider ?? "provider"} / {data.model}
        </p>
        <Button
          variant={isFailedReview ? "danger" : "ghost"}
          disabled={isInFlight}
          onClick={() => rerunMutation.mutate({ reviewId, installationId })}
          style={{ marginTop: "0.75rem" }}
        >
          {isInFlight ? "Review in progress…" : isFailedReview ? "Retry review" : "Re-run review"}
        </Button>
      </Panel>

      <ActionChain
        audits={audits}
        debugArtifacts={data.debug_artifacts ?? null}
        costUsd={data.cost_usd}
        postedFindingsCount={postedFindingsCount}
        pipelineStagedFindingsPeak={pipelineStagedFindingsPeak}
        pipelineEmptyHint={pipelineEmptyHint}
        getDebugExportPayload={getDebugExportPayload}
      />

      {postedFindingsCount > 0 ? (
        <div className="review-workspace-grid panel panel-elevated">
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
      ) : (
        <Panel>
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
            No inline findings to show in the diff panels. Use the action chain above for pipeline detail and token cost.
          </p>
        </Panel>
      )}

      <ReviewTimeline events={events} />
    </section>
  );
}
