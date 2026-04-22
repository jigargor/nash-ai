export type ReviewStatus = "queued" | "running" | "done" | "failed";
export type Severity = "critical" | "high" | "medium" | "low";
export type Category = "security" | "performance" | "correctness" | "style" | "maintainability";
export type Evidence = "tool_verified" | "diff_visible" | "verified_fact" | "inference";

export interface Finding {
  severity: Severity;
  category: Category;
  message: string;
  file_path: string;
  line_start: number;
  line_end?: number;
  suggestion?: string;
  confidence: number;
  evidence: Evidence;
  evidence_tool_calls?: string[] | null;
  evidence_fact_id?: string | null;
  is_vendor_claim?: boolean;
}

export interface FindingOutcome {
  finding_index: number;
  github_comment_id: number | null;
  outcome:
    | "applied_directly"
    | "applied_modified"
    | "acknowledged"
    | "dismissed"
    | "ignored"
    | "abandoned"
    | "superseded"
    | "pending";
  outcome_confidence: "high" | "medium" | "low";
  detected_at: string | null;
  signals: Record<string, unknown>;
}

export interface ReviewResult {
  findings: Finding[];
  summary: string;
  tokens_used: number;
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
