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

export function generateRepoTemplate(owner: string, repo: string, installationId: number) {
  return apiFetch<GeneratedRepoTemplate>(
    `/api/v1/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/codereview-template/generate?installation_id=${installationId}`,
    { method: "POST" },
  );
}

export const CODEREVIEW_TEMPLATE_EXAMPLE = `# .codereview.yml
# Balanced defaults: good precision, reasonable cost, max_mode on.
#
# PR controls (title or description, case-insensitive):
#   [skip-nash-review]  — do not enqueue an automated review for this PR
#   [force-nash-review] — if both tags appear, review still runs

confidence_threshold: 0.88
severity_threshold: medium
categories:
  - security
  - correctness
  - performance
review_drafts: false
max_findings_per_pr: 20

prompt_additions: |
  Prefer minimal, safe fixes.
  Avoid style-only comments unless they affect maintainability.

ignore_paths:
  - "**/*.snap"
  - "**/dist/**"
  - "**/build/**"
  - "**/coverage/**"
  - "**/*.min.js"
  - "**/*.lock"

model:
  provider: anthropic
  name: claude-sonnet-4-5

max_mode:
  enabled: true
  conflict_threshold: 35
  high_risk_severity: high
  challenger:
    provider: openai
    name: gpt-5.5
  tie_break:
    provider: gemini
    name: gemini-2.5-pro

chunking:
  enabled: true
  proactive_threshold_tokens: 35000
  target_chunk_tokens: 18000
  max_chunks: 8`;
