import { apiFetch } from "@/lib/api/client";

export interface RepoInstallation {
  installation_id: number;
  account_login: string;
  account_type: string;
  active: boolean;
  suspended_at: string | null;
}

export interface RepoSummary {
  installation_id: number;
  repo_full_name: string;
  review_count: number;
  failed_review_count: number;
  total_tokens: number;
  estimated_cost_usd: string;
  latest_review_id: number;
  latest_pr_number: number;
  latest_status: string;
  last_review_at: string;
}

export function fetchInstallations() {
  return apiFetch<RepoInstallation[]>("/api/v1/installations");
}

export function fetchRepos(installationId?: number) {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return apiFetch<RepoSummary[]>(`/api/v1/repos${suffix}`);
}
