import { apiFetch } from "@/lib/api/client";

export interface ExternalEvalEstimateRequest {
  installation_id: number;
  repo_url: string;
  target_ref?: string;
}

export interface ExternalEvalEstimate {
  owner: string;
  repo: string;
  target_ref: string;
  default_branch: string;
  file_count: number;
  total_bytes: number;
  estimated_tokens: number;
  estimated_cost_usd: string;
  ack_required: boolean;
  warning: string;
}

export interface ExternalEvalCreateRequest extends ExternalEvalEstimateRequest {
  ack_confirmed: boolean;
  token_budget_cap: number;
  cost_budget_cap_usd: number;
}

export interface ExternalEvalListItem {
  id: number;
  installation_id: number;
  repo_url: string;
  owner: string;
  repo: string;
  target_ref: string;
  status: string;
  estimated_tokens: number;
  estimated_cost_usd: string;
  token_budget_cap: number;
  cost_budget_cap_usd: string;
  findings_count: number;
  tokens_used: number;
  cost_usd: string;
  summary: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface ExternalEvalDetail extends ExternalEvalListItem {
  prepass_metadata: Record<string, unknown> | null;
  shards: Array<{
    id: number;
    shard_key: string;
    status: string;
    model_tier: string;
    file_count: number;
    findings_count: number;
    tokens_used: number;
    cost_usd: string;
  }>;
  findings: Array<{
    id: number;
    category: string;
    severity: string;
    title: string;
    message: string;
    file_path: string | null;
    line_start: number | null;
    line_end: number | null;
    evidence: Record<string, unknown>;
  }>;
}

export function estimateExternalEval(payload: ExternalEvalEstimateRequest) {
  return apiFetch<ExternalEvalEstimate>("/api/v1/external-evals/estimate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createExternalEval(payload: ExternalEvalCreateRequest) {
  return apiFetch<{ ok: boolean; external_eval_id: number; status: string }>("/api/v1/external-evals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchExternalEvals(installationId: number) {
  return apiFetch<ExternalEvalListItem[]>(`/api/v1/external-evals?installation_id=${installationId}`);
}

export function fetchExternalEvalDetail(externalEvalId: number, installationId: number) {
  return apiFetch<ExternalEvalDetail>(`/api/v1/external-evals/${externalEvalId}?installation_id=${installationId}`);
}

export function cancelExternalEval(externalEvalId: number, installationId: number) {
  return apiFetch<{ ok: boolean; external_eval_id: number; status: string }>(
    `/api/v1/external-evals/${externalEvalId}/cancel`,
    {
      method: "POST",
      body: JSON.stringify({ installation_id: installationId }),
    },
  );
}

