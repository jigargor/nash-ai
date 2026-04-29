"use client";

import type { Finding } from "@ai-code-review/shared-types";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

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
import type { ReviewModelAudit } from "@/lib/api/reviews";
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

interface ModelUsageEntry {
  key: string;
  label: string;
  failed: boolean;
}

interface ReviewRunHistoryEntry {
  runId: string;
  startedAt: string | null;
  stageCount: number;
}

function stageLooksFailed(audit: ReviewModelAudit): boolean {
  if (audit.decision.toLowerCase().includes("error")) return true;
  const metadata = audit.metadata_json;
  if (!metadata || typeof metadata !== "object") return false;
  const reason = metadata.reason;
  if (typeof reason === "string") {
    const lowered = reason.toLowerCase();
    if (lowered.includes("failed") || lowered.includes("error")) return true;
  }
  return false;
}

function modelUsageFromAudits(audits: ReviewModelAudit[]): ModelUsageEntry[] {
  const entries: ModelUsageEntry[] = [];
  for (const audit of audits) {
    entries.push({
      key: `${audit.id}:${audit.provider}:${audit.model}`,
      label: `${audit.provider} / ${audit.model}`,
      failed: stageLooksFailed(audit),
    });
  }
  return entries;
}

function nonSelectionReason(
  provider: string,
  debugArtifacts: Record<string, unknown> | null | undefined,
): string | null {
  const resolutions = debugArtifacts?.llm_model_resolutions as Record<string, unknown> | undefined;
  if (!resolutions || typeof resolutions !== "object") return null;
  const attemptLists = Object.entries(resolutions)
    .filter(([key, value]) => key.endsWith("_attempts") && Array.isArray(value))
    .map(([, value]) => value as unknown[]);
  if (!attemptLists.length) return null;

  const providerAttempted = attemptLists.some((attempts) =>
    attempts.some(
      (attempt) =>
        typeof attempt === "object" &&
        attempt !== null &&
        "provider" in attempt &&
        String((attempt as Record<string, unknown>).provider) === provider,
    ),
  );
  if (!providerAttempted) return "Not present in this run's eligible attempt chain.";

  const earlierSuccess = attemptLists.some((attempts) => {
    const index = attempts.findIndex(
      (attempt) =>
        typeof attempt === "object" &&
        attempt !== null &&
        "provider" in attempt &&
        String((attempt as Record<string, unknown>).provider) === provider,
    );
    return index > 0;
  });
  if (earlierSuccess)
    return "Listed later in fallback order; an earlier provider succeeded before this one was needed.";
  return "Configured but not selected by routing policy for this run.";
}

function runHistoryFromAudits(audits: ReviewModelAudit[]): ReviewRunHistoryEntry[] {
  const byRun = new Map<string, { startedAt: string | null; stageCount: number }>();
  for (const audit of audits) {
    if (!audit.run_id) continue;
    const existing = byRun.get(audit.run_id);
    if (!existing) {
      byRun.set(audit.run_id, { startedAt: audit.created_at, stageCount: 1 });
      continue;
    }
    existing.stageCount += 1;
    if (audit.created_at && (!existing.startedAt || audit.created_at < existing.startedAt))
      existing.startedAt = audit.created_at;
  }
  return Array.from(byRun.entries())
    .map(([runId, meta]) => ({ runId, startedAt: meta.startedAt, stageCount: meta.stageCount }))
    .sort((left, right) => (right.startedAt ?? "").localeCompare(left.startedAt ?? ""));
}

function ModelUsageHover({ entries }: { entries: ModelUsageEntry[] }) {
  if (!entries.length)
    return (
      <span style={{ color: "var(--text-muted)", marginBottom: 0, marginTop: "0.45rem", fontSize: "0.85rem" }}>
        Models used: unavailable
      </span>
    );
  return (
    <div
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        marginTop: "0.45rem",
      }}
    >
      <span
        style={{
          color: "var(--text-muted)",
          fontSize: "0.85rem",
          borderBottom: "1px dashed var(--border-strong)",
          cursor: "help",
        }}
      >
        Models used ({entries.length})
      </span>
      <div
        style={{
          position: "absolute",
          top: "1.5rem",
          left: 0,
          minWidth: "20rem",
          padding: "0.55rem 0.65rem",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border-strong)",
          background: "var(--card)",
          boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
          display: "none",
          zIndex: 20,
        }}
        className="model-usage-hover-menu"
      >
        <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.72rem", marginBottom: "0.35rem" }}>
          Execution order
        </p>
        <ol style={{ margin: 0, paddingLeft: "1rem", display: "grid", gap: "0.18rem" }}>
          {entries.map((entry) => (
            <li
              key={entry.key}
              style={{
                color: "var(--text-primary)",
                fontSize: "0.8rem",
                textDecoration: entry.failed ? "line-through" : "none",
                opacity: entry.failed ? 0.7 : 1,
              }}
            >
              {entry.label}
            </li>
          ))}
        </ol>
      </div>
      <style jsx>{`
        div:hover > .model-usage-hover-menu {
          display: block;
        }
      `}</style>
    </div>
  );
}

function ProviderAvailabilityIndicator({
  audits,
  debugArtifacts,
}: {
  audits: ReviewModelAudit[];
  debugArtifacts: Record<string, unknown> | null | undefined;
}) {
  const availability = (debugArtifacts?.provider_availability as Record<string, unknown> | undefined) ?? {};
  const providersMap = (availability.providers as Record<string, unknown> | undefined) ?? {};
  const providers = ["anthropic", "openai", "gemini"] as const;

  const attempted = new Set(audits.map((audit) => audit.provider));
  const allByProvider = new Map<string, ReviewModelAudit[]>();
  for (const audit of audits) {
    const rows = allByProvider.get(audit.provider);
    if (rows) rows.push(audit);
    else allByProvider.set(audit.provider, [audit]);
  }

  const tokens = providers.map((provider) => {
    const configEntry = providersMap[provider];
    const configured =
      typeof configEntry === "object" &&
      configEntry !== null &&
      "configured" in configEntry &&
      Boolean((configEntry as Record<string, unknown>).configured);
    const attempts = allByProvider.get(provider) ?? [];
    const hasAttempts = attempted.has(provider);
    const allFailed = hasAttempts && attempts.every((audit) => stageLooksFailed(audit));
    const label = !configured
      ? "not configured"
      : allFailed
      ? "runtime failure"
      : hasAttempts
      ? "used"
      : "configured, not selected";
    const tooltip = !configured || hasAttempts ? null : nonSelectionReason(provider, debugArtifacts);
    const color = !configured
      ? "var(--text-muted)"
      : allFailed
      ? "#f43f5e"
      : hasAttempts
      ? "var(--success)"
      : "var(--text-muted)";
    return (
      <span key={provider} style={{ color }} title={tooltip ?? undefined}>
        {provider}: {label}
      </span>
    );
  });

  return (
    <p style={{ marginBottom: 0, marginTop: "0.35rem", fontSize: "0.78rem", display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>
      {tokens}
    </p>
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
  const [userSelectedRunId, setUserSelectedRunId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

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
  const runHistory = useMemo(() => runHistoryFromAudits(audits), [audits]);
  const latestRunId = runHistory[0]?.runId ?? null;
  const selectedRunId = useMemo(() => {
    if (isInFlight) return null;
    if (userSelectedRunId && runHistory.some((run) => run.runId === userSelectedRunId))
      return userSelectedRunId;
    return latestRunId;
  }, [isInFlight, userSelectedRunId, runHistory, latestRunId]);
  const currentRunAudits = useMemo(() => {
    if (isInFlight) {
      const startedAt = reviewQuery.data?.started_at;
      if (!startedAt) return [];
      return audits.filter((audit) => Boolean(audit.created_at && audit.created_at >= startedAt));
    }
    if (selectedRunId) return audits.filter((audit) => audit.run_id === selectedRunId);
    return latestRunId ? audits.filter((audit) => audit.run_id === latestRunId) : audits;
  }, [isInFlight, reviewQuery.data?.started_at, audits, selectedRunId, latestRunId]);
  const modelUsageEntries = useMemo(() => modelUsageFromAudits(currentRunAudits), [currentRunAudits]);
  const pipelineStagedFindingsPeak = useMemo(
    () =>
      currentRunAudits.reduce(
        (max, a) => (typeof a.findings_count === "number" ? Math.max(max, a.findings_count) : max),
        0,
      ),
    [currentRunAudits],
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
    const modelAuditsList = currentRunAudits;
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
    currentRunAudits,
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
          Primary model: {data.model_provider ?? "provider"} / {data.model}
        </p>
        <ModelUsageHover entries={modelUsageEntries} />
        <ProviderAvailabilityIndicator audits={currentRunAudits} debugArtifacts={data.debug_artifacts} />
        <div
          style={{
            marginTop: "0.45rem",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "1rem",
            rowGap: "0.5rem",
            width: "100%",
          }}
        >
          <div style={{ display: "inline-flex", alignItems: "center", gap: "0.9rem", flexWrap: "wrap" }}>
            <div style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: "0.45rem", flexShrink: 0 }}>
              <button
                type="button"
                onClick={() => setHistoryOpen((open) => !open)}
                aria-label="Show run history"
                title="Run history"
                style={{
                  width: "2rem",
                  height: "2rem",
                  borderRadius: "999px",
                  border: "1px solid var(--border-strong)",
                  background: "var(--card-muted)",
                  color: "var(--text-muted)",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <path d="M3 12a9 9 0 1 0 3-6.7" />
                  <polyline points="3 3 3 9 9 9" />
                  <path d="M12 7v5l3 3" />
                </svg>
              </button>
              <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
                {isInFlight ? "Current run" : selectedRunId ? `Run ${selectedRunId.slice(0, 8)}` : "Run history"}
              </span>
              {historyOpen && runHistory.length > 0 && !isInFlight ? (
                <div style={{ position: "absolute", top: "2.2rem", left: 0, zIndex: 30, border: "1px solid var(--border-strong)", borderRadius: "var(--radius-md)", background: "var(--card)", minWidth: "15rem", padding: "0.45rem" }}>
                  {runHistory.map((run) => (
                    <button
                      key={run.runId}
                      type="button"
                      onClick={() => {
                        setUserSelectedRunId(run.runId);
                        setHistoryOpen(false);
                      }}
                      style={{
                        width: "100%",
                        textAlign: "left",
                        border: "none",
                        background: selectedRunId === run.runId ? "var(--accent-muted)" : "transparent",
                        color: "inherit",
                        borderRadius: "var(--radius-sm)",
                        padding: "0.4rem 0.45rem",
                        cursor: "pointer",
                        fontSize: "0.78rem",
                      }}
                    >
                      <div>{run.startedAt ? new Date(run.startedAt).toLocaleString() : "Unknown date"}</div>
                      <div style={{ color: "var(--text-muted)", fontSize: "0.72rem" }}>
                        {run.stageCount} stage{run.stageCount === 1 ? "" : "s"} · {run.runId.slice(0, 8)}
                      </div>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
          <Button
            variant={isFailedReview ? "danger" : "ghost"}
            disabled={isInFlight}
            onClick={() => {
              setUserSelectedRunId(null);
              setHistoryOpen(false);
              rerunMutation.mutate({ reviewId, installationId });
            }}
          >
            {isInFlight ? "Review in progress…" : isFailedReview ? "Retry review" : "Re-run review"}
          </Button>
        </div>
      </Panel>

      <ActionChain
        audits={currentRunAudits}
        debugArtifacts={data.debug_artifacts ?? null}
        isInFlight={isInFlight}
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

      <ReviewTimeline
        events={events}
        reviewStartedAt={data.started_at ?? data.created_at}
        reviewCompletedAt={data.completed_at}
        isInFlight={isInFlight}
      />
    </section>
  );
}
