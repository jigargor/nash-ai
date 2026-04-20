import { apiFetch } from "@/lib/api/client";
import type { Finding } from "@ai-code-review/shared-types";

export interface ReviewListItem {
  id: number;
  repo_full_name: string;
  pr_number: number;
  status: string;
  tokens_used: number | null;
  cost_usd: string | null;
}

export interface ReviewDetail {
  id: number;
  installation_id: number;
  repo_full_name: string;
  pr_number: number;
  pr_head_sha: string;
  status: string;
  model: string;
  findings: {
    findings: Finding[];
    summary: string;
  } | null;
  tokens_used: number | null;
  cost_usd: string | null;
  created_at: string;
  completed_at: string | null;
}

export function fetchReviews(installationId?: number) {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return apiFetch<ReviewListItem[]>(`/api/v1/reviews${suffix}`);
}

export function fetchReview(reviewId: number, installationId?: number) {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return apiFetch<ReviewDetail>(`/api/v1/reviews/${reviewId}${suffix}`);
}

export function rerunReview(reviewId: number) {
  return apiFetch<{ ok: boolean; review_id: number }>(`/api/v1/reviews/${reviewId}/rerun`, {
    method: "POST",
  });
}

export function dismissFinding(reviewId: number, findingIndex: number) {
  return apiFetch<{ ok: boolean; review_id: number; dismissed_finding_index: number }>(
    `/api/v1/reviews/${reviewId}/findings/${findingIndex}/dismiss`,
    {
      method: "POST",
    },
  );
}
