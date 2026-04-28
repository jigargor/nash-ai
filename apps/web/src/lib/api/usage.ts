import { apiFetch } from "@/lib/api/client";

export interface UsageBucket {
  bucket: string;
  requests: number;
}

export interface ServiceUsagePoint {
  service: string;
  requests: number;
}

export interface UsageSummary {
  installation_id: number;
  service_breakdown: ServiceUsagePoint[];
  daily_requests: UsageBucket[];
  weekly_requests: UsageBucket[];
  token_usage: {
    daily: number;
    weekly: number;
  };
  session_cap: {
    daily_token_budget: number;
    daily_used: number;
    remaining: number;
    state: "safe" | "near-cap" | "capped";
  };
  api_key_caps: Array<{
    provider: string;
    daily_tokens: number;
    weekly_tokens: number;
    daily_cost_usd: string;
    weekly_cost_usd: string;
    effective_cap_tokens: number;
  }>;
  cumulative_caps: {
    daily_tokens: number;
    weekly_tokens: number;
    daily_token_budget: number;
    state: "safe" | "near-cap" | "capped";
  };
}

export function fetchUsageSummary(installationId: number) {
  return apiFetch<UsageSummary>(`/api/v1/usage/summary?installation_id=${installationId}`);
}

