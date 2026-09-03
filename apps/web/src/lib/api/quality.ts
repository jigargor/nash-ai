import type { Category, Severity } from "@ai-code-review/shared-types";

/** Human quality labels (mirrors FindingLabelValue in apps/api/src/app/api/finding_labels.py). */
export const FINDING_LABEL_VALUES = [
  "true_positive",
  "false_positive",
  "severity_wrong",
  "category_wrong",
  "duplicate",
  "not_actionable",
  "correct_but_too_minor",
  "accepted",
  "accepted_with_modification",
] as const;

export type FindingLabelValue = (typeof FINDING_LABEL_VALUES)[number];

export interface FindingLabelResponse {
  review_id: number;
  finding_index: number;
  installation_id: number;
  label: FindingLabelValue | string;
  notes: string | null;
  labeled_by_user_id: number | null;
  labeled_at: string;
  updated_at: string;
}

export const MISSED_ISSUE_HOW_FOUND = [
  "manual_report",
  "bug_fix",
  "static_analyzer",
  "security_scan",
  "test_failure",
  "maintainer_review",
] as const;

export type MissedIssueHowFound = (typeof MISSED_ISSUE_HOW_FOUND)[number];

export interface MissedIssueCreateRequest {
  review_id: number;
  file_path: string;
  line_start: number;
  line_end?: number | null;
  description: string;
  expected_category: Category;
  expected_severity: Severity;
  how_found: MissedIssueHowFound;
  notes?: string | null;
}

export interface MissedIssueResponse {
  id: number;
  review_id: number;
  installation_id: number;
  file_path: string;
  line_start: number;
  line_end: number | null;
  description: string;
  expected_category: string;
  expected_severity: string;
  how_found: string;
  notes: string | null;
  created_at: string;
}

export interface FastPathScorecard {
  installation_id: number;
  repo_full_name: string | null;
  window_days: number;
  total_fast_path_calls: number;
  fast_path_accept_rate: number;
  disagreement_rate: number;
  dismiss_rate: number;
  ignore_rate: number;
  useful_rate: number;
  threshold_lowering_authorized: boolean;
}

export interface CostPerFindingSummary {
  summary: {
    total_cost_usd: number;
    total_true_positives: number;
    overall_cost_per_tp_usd: number | null;
    reviews_analyzed: number;
  };
  reviews: Array<{
    review_id: number;
    repo_full_name: string;
    model: string | null;
    cost_usd: number | null;
    true_positive_findings: number;
    cost_per_tp_usd: number | null;
    completed_at: string | null;
  }>;
}

/** A finding removed by a pipeline stage (mirrors DroppedFinding in schema.py). */
export interface DroppedFindingArtifact {
  finding: Record<string, unknown> | null;
  reason: string;
  detail?: string | null;
  stage: string;
}

/** Legacy runner artifact shape (debug_artifacts.validator_dropped). */
export interface LegacyValidatorDrop {
  file_path: string;
  line_start: number;
  line_end?: number;
  reason: string;
  detail?: string;
  message_excerpt?: string;
}

export interface DropReasonBucket {
  key: string;
  stage: string;
  reason: string;
  count: number;
  samples: Array<{ file_path: string; line_start: number; detail: string }>;
}

/** Normalise both the pipeline (`drops`) and legacy runner drop artifacts into buckets. */
export function collectDropBuckets(debugArtifacts: Record<string, unknown> | null | undefined): DropReasonBucket[] {
  if (!debugArtifacts) return [];
  const buckets = new Map<string, DropReasonBucket>();

  function push(stage: string, reason: string, filePath: string, lineStart: number, detail: string): void {
    const key = `${stage}:${reason}`;
    const bucket = buckets.get(key) ?? { key, stage, reason, count: 0, samples: [] };
    bucket.count += 1;
    if (bucket.samples.length < 3) bucket.samples.push({ file_path: filePath, line_start: lineStart, detail });
    buckets.set(key, bucket);
  }

  const drops = debugArtifacts.drops;
  if (Array.isArray(drops)) {
    for (const raw of drops) {
      if (!raw || typeof raw !== "object") continue;
      const drop = raw as DroppedFindingArtifact;
      const finding = drop.finding ?? {};
      push(
        drop.stage || "validation",
        drop.reason || "unknown",
        typeof finding.file_path === "string" ? finding.file_path : "",
        typeof finding.line_start === "number" ? finding.line_start : 0,
        drop.detail ?? "",
      );
    }
  }
  const legacy = debugArtifacts.validator_dropped;
  if (Array.isArray(legacy)) {
    for (const raw of legacy) {
      if (!raw || typeof raw !== "object") continue;
      const drop = raw as LegacyValidatorDrop;
      push("validation", drop.reason || "unknown", drop.file_path, drop.line_start, drop.detail ?? drop.message_excerpt ?? "");
    }
  }
  const confidence = debugArtifacts.confidence_dropped;
  if (Array.isArray(confidence)) {
    for (const raw of confidence) {
      if (!raw || typeof raw !== "object") continue;
      const drop = raw as { file_path?: string; line_start?: number; confidence?: number; threshold?: number };
      push(
        "policy",
        "below_confidence_threshold",
        drop.file_path ?? "",
        drop.line_start ?? 0,
        `confidence ${drop.confidence ?? "?"} < threshold ${drop.threshold ?? "?"}`,
      );
    }
  }
  const editorDrops = debugArtifacts.editor_drop_reasons;
  if (editorDrops && typeof editorDrops === "object") {
    for (const [reason, count] of Object.entries(editorDrops as Record<string, unknown>)) {
      if (typeof count !== "number") continue;
      for (let i = 0; i < count; i += 1) push("editor", reason, "", 0, "");
    }
  }
  return [...buckets.values()].sort((a, b) => b.count - a.count);
}
