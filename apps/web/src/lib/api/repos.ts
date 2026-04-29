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
  ai_template_generated: boolean;
  ai_template_generated_at: string | null;
}

export interface GeneratedRepoTemplate {
  repo_full_name: string;
  generated_once: boolean;
  generated_at: string;
  provider: string;
  model: string;
  config_yaml_text: string;
}

export function fetchInstallations() {
  return apiFetch<RepoInstallation[]>("/api/v1/installations");
}

export function fetchRepos(installationId?: number) {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return apiFetch<RepoSummary[]>(`/api/v1/repos${suffix}`);
}

export interface CodeReviewConfigResult {
  found: boolean;
  yaml_text: string | null;
  config_json: Record<string, unknown> | null;
}

export function fetchCodeReviewConfig(owner: string, repo: string, installationId: number) {
  return apiFetch<CodeReviewConfigResult>(
    `/api/v1/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/codereview-config?installation_id=${installationId}`,
  );
}

export function generateRepoTemplate(owner: string, repo: string, installationId: number) {
  return apiFetch<GeneratedRepoTemplate>(
    `/api/v1/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/codereview-template/generate?installation_id=${installationId}`,
    { method: "POST" },
  );
}
