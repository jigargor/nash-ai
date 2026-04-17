export type ReviewStatus = "queued" | "running" | "done" | "failed";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Category = "security" | "performance" | "correctness" | "style" | "maintainability";

export interface Finding {
  severity: Severity;
  category: Category;
  message: string;
  file_path: string;
  line_start: number;
  line_end?: number;
  suggestion?: string;
  confidence: number;
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
