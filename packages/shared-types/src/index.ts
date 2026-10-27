export type {
  Category,
  DiffSide,
  DropReason,
  Evidence,
  Finding,
  ReviewStatus,
  Severity,
  TerminalStatus,
} from "./generated";
export { CATEGORIES, DROP_REASONS, REVIEW_STATUSES, SEVERITIES } from "./generated";

import type { Finding, ReviewStatus } from "./generated";

export type FindingOutcomeValue =
  | "applied_directly"
  | "applied_modified"
  | "acknowledged"
  | "dismissed"
  | "ignored"
  | "abandoned"
  | "superseded"
  | "pending";

export interface FindingOutcome {
  finding_index: number;
  github_comment_id: number | null;
  outcome: FindingOutcomeValue;
  outcome_confidence: "high" | "medium" | "low";
  detected_at: string | null;
  signals: Record<string, unknown>;
}

/** Canonical telemetry event emitted per classifier outcome (see ARCHITECTURE.md). */
export const OUTCOME_EVENTS: Record<FindingOutcomeValue, string | null> = {
  applied_directly: "suggestion.accepted",
  applied_modified: "suggestion.edited",
  dismissed: "suggestion.dismissed",
  acknowledged: "finding.resolved",
  superseded: "finding.resolved",
  ignored: "finding.ignored",
  abandoned: "finding.ignored",
  pending: null,
};

export interface DroppedFinding {
  finding: Record<string, unknown> | null;
  reason: string;
  detail?: string | null;
  stage: string;
}

export interface ReviewResult {
  findings: Finding[];
  summary: string;
  tokens_used: number;
  model_provider?: "anthropic" | "openai" | "gemini";
  model: string;
}

export interface Review {
  id: number;
  repo_full_name: string;
  pr_number: number;
  pr_head_sha: string;
  status: ReviewStatus;
  result?: ReviewResult;
  created_at: string;
  completed_at?: string;
}
