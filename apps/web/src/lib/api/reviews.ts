import { apiFetch } from "@/lib/api/client";
import type { Finding, FindingOutcome } from "@ai-code-review/shared-types";

export interface ReviewListItem {
  id: number;
  installation_id: number;
  repo_full_name: string;
  pr_number: number;
  status: string;
  model_provider?: string | null;
  model?: string | null;
  tokens_used: number | null;
  cost_usd: string | null;
  findings_count?: number;
  files_changed?: number | null;
  lines_changed?: number | null;
}

export interface ReviewDetail {
  id: number;
  installation_id: number;
  repo_full_name: string;
  pr_number: number;
  pr_head_sha: string;
  status: string;
  model_provider?: string | null;
  model: string;
  findings: {
    findings: Finding[];
    summary: string;
  } | null;
  tokens_used: number | null;
  cost_usd: string | null;
  created_at: string;
  completed_at: string | null;
  finding_outcomes: FindingOutcome[];
  debug_artifacts: Record<string, unknown> | null;
}

export interface ReviewOutcomeResponse {
  review_id: number;
  finding_outcomes: FindingOutcome[];
}

export interface ReviewModelAudit {
  id: number;
  run_id: string;
  stage: string;
  provider: string;
  model: string;
  prompt_version: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  findings_count: number | null;
  accepted_findings_count: number | null;
  conflict_score: number | null;
  decision: string;
  stage_duration_ms: number | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string | null;
}

export interface ReviewModelAuditsResponse {
  review_id: number;
  model_audits: ReviewModelAudit[];
}

export function fetchReviews(installationId?: number) {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return apiFetch<ReviewListItem[]>(`/api/v1/reviews${suffix}`);
}

export function fetchReview(reviewId: number, installationId?: number) {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return apiFetch<ReviewDetail>(`/api/v1/reviews/${reviewId}${suffix}`);
}

export function fetchReviewOutcomes(reviewId: number, installationId?: number) {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return apiFetch<ReviewOutcomeResponse>(`/api/v1/reviews/${reviewId}/outcomes${suffix}`);
}

export function fetchReviewModelAudits(reviewId: number, installationId?: number) {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return apiFetch<ReviewModelAuditsResponse>(`/api/v1/reviews/${reviewId}/model-audits${suffix}`);
}

export interface OutcomeSummary {
  total_classified: number;
  outcomes: Record<string, number>;
  global_metrics: {
    applied_rate: number;
    dismiss_rate: number;
    ignore_rate: number;
    positive_rate: number;
    useful_rate: number;
  };
  breakdowns: Record<string, Record<string, Record<string, number>>>;
}

export function fetchOutcomeSummary(installationId?: number, repoFullName?: string) {
  const params = new URLSearchParams();
  if (installationId) params.set("installation_id", String(installationId));
  if (repoFullName) params.set("repo_full_name", repoFullName);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<OutcomeSummary>(`/api/v1/telemetry/outcomes/summary${suffix}`);
}

export function rerunReview(reviewId: number, installationId: number) {
  return apiFetch<{ ok: boolean; review_id: number }>(`/api/v1/reviews/${reviewId}/rerun?installation_id=${installationId}`, {
    method: "POST",
  });
}

export function dismissFinding(reviewId: number, findingIndex: number, installationId: number) {
  return apiFetch<{ ok: boolean; review_id: number; dismissed_finding_index: number }>(
    `/api/v1/reviews/${reviewId}/findings/${findingIndex}/dismiss?installation_id=${installationId}`,
    {
      method: "POST",
    },
  );
}
