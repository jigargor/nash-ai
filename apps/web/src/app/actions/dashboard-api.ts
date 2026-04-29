"use server";

import { serverBffFetch } from "@/lib/api/server-bff-fetch";
import type { AuthMeResponse, TermsStatusResponse } from "@/lib/api/auth";
import type {
  ExternalEvalCreateRequest,
  ExternalEvalDetail,
  ExternalEvalEstimate,
  ExternalEvalEstimateRequest,
  ExternalEvalListItem,
} from "@/lib/api/external-evals";
import type { ModelsCatalogResponse } from "@/lib/api/models";
import type { CodeReviewConfigResult, GeneratedRepoTemplate, RepoInstallation, RepoSummary } from "@/lib/api/repos";
import type {
  OutcomeSummary,
  ReviewDetail,
  ReviewListFilters,
  ReviewListItem,
  ReviewModelAuditsResponse,
  ReviewOutcomeResponse,
} from "@/lib/api/reviews";
import type { KeyStatus } from "@/lib/api/user-keys";
import type { UsageSummary } from "@/lib/api/usage";

export async function actionFetchInstallations(): Promise<RepoInstallation[]> {
  return serverBffFetch<RepoInstallation[]>("/api/v1/installations");
}

export async function actionFetchRepos(installationId?: number): Promise<RepoSummary[]> {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return serverBffFetch<RepoSummary[]>(`/api/v1/repos${suffix}`);
}

export async function actionFetchCodeReviewConfig(
  owner: string,
  repo: string,
  installationId: number,
): Promise<CodeReviewConfigResult> {
  return serverBffFetch<CodeReviewConfigResult>(
    `/api/v1/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/codereview-config?installation_id=${installationId}`,
  );
}

export async function actionGenerateRepoTemplate(
  owner: string,
  repo: string,
  installationId: number,
): Promise<GeneratedRepoTemplate> {
  return serverBffFetch<GeneratedRepoTemplate>(
    `/api/v1/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/codereview-template/generate?installation_id=${installationId}`,
    { method: "POST" },
  );
}

export async function actionFetchReviews(
  installationId?: number,
  filters?: ReviewListFilters,
): Promise<ReviewListItem[]> {
  const params = new URLSearchParams();
  if (installationId) params.set("installation_id", String(installationId));
  if (filters?.createdAfter) params.set("created_after", filters.createdAfter);
  if (filters?.createdBefore) params.set("created_before", filters.createdBefore);
  if (filters?.status && filters.status !== "all") params.set("status", filters.status);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return serverBffFetch<ReviewListItem[]>(`/api/v1/reviews${suffix}`);
}

export async function actionFetchReview(reviewId: number, installationId?: number): Promise<ReviewDetail> {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return serverBffFetch<ReviewDetail>(`/api/v1/reviews/${reviewId}${suffix}`);
}

export async function actionFetchReviewOutcomes(
  reviewId: number,
  installationId?: number,
): Promise<ReviewOutcomeResponse> {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return serverBffFetch<ReviewOutcomeResponse>(`/api/v1/reviews/${reviewId}/outcomes${suffix}`);
}

export async function actionFetchReviewModelAudits(
  reviewId: number,
  installationId?: number,
): Promise<ReviewModelAuditsResponse> {
  const suffix = installationId ? `?installation_id=${installationId}` : "";
  return serverBffFetch<ReviewModelAuditsResponse>(`/api/v1/reviews/${reviewId}/model-audits${suffix}`);
}

export async function actionFetchOutcomeSummary(
  installationId?: number,
  repoFullName?: string,
): Promise<OutcomeSummary> {
  const params = new URLSearchParams();
  if (installationId) params.set("installation_id", String(installationId));
  if (repoFullName) params.set("repo_full_name", repoFullName);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return serverBffFetch<OutcomeSummary>(`/api/v1/telemetry/outcomes/summary${suffix}`);
}

export async function actionRerunReview(
  reviewId: number,
  installationId: number,
): Promise<{ ok: boolean; review_id: number }> {
  return serverBffFetch<{ ok: boolean; review_id: number }>(
    `/api/v1/reviews/${reviewId}/rerun?installation_id=${installationId}`,
    { method: "POST" },
  );
}

export async function actionDismissFinding(
  reviewId: number,
  findingIndex: number,
  installationId: number,
): Promise<{ ok: boolean; review_id: number; dismissed_finding_index: number }> {
  return serverBffFetch<{ ok: boolean; review_id: number; dismissed_finding_index: number }>(
    `/api/v1/reviews/${reviewId}/findings/${findingIndex}/dismiss?installation_id=${installationId}`,
    { method: "POST" },
  );
}

export async function actionFetchCurrentUser(): Promise<AuthMeResponse> {
  return serverBffFetch<AuthMeResponse>("/api/v1/auth/me");
}

export async function actionFetchTermsStatus(): Promise<TermsStatusResponse> {
  return serverBffFetch<TermsStatusResponse>("/api/v1/users/me/terms-status");
}

export async function actionAcceptTerms(): Promise<TermsStatusResponse> {
  return serverBffFetch<TermsStatusResponse>("/api/v1/users/me/terms-acceptance", {
    method: "POST",
  });
}

export async function actionFetchModelsCatalog(): Promise<ModelsCatalogResponse> {
  return serverBffFetch<ModelsCatalogResponse>("/api/v1/models/catalog");
}

export async function actionFetchUsageSummary(installationId: number): Promise<UsageSummary> {
  return serverBffFetch<UsageSummary>(`/api/v1/usage/summary?installation_id=${installationId}`);
}

export async function actionFetchUserKeys(): Promise<KeyStatus[]> {
  return serverBffFetch<KeyStatus[]>("/api/v1/users/me/keys");
}

export async function actionUpsertUserKey(provider: string, apiKey: string): Promise<{ detail: string }> {
  return serverBffFetch<{ detail: string }>(`/api/v1/users/me/keys/${provider}`, {
    method: "PUT",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function actionDeleteUserKey(provider: string): Promise<{ detail: string }> {
  return serverBffFetch<{ detail: string }>(`/api/v1/users/me/keys/${provider}`, {
    method: "DELETE",
  });
}

export async function actionEstimateExternalEval(payload: ExternalEvalEstimateRequest): Promise<ExternalEvalEstimate> {
  return serverBffFetch<ExternalEvalEstimate>("/api/v1/external-evals/estimate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function actionCreateExternalEval(
  payload: ExternalEvalCreateRequest,
): Promise<{ ok: boolean; external_eval_id: number; status: string }> {
  return serverBffFetch<{ ok: boolean; external_eval_id: number; status: string }>("/api/v1/external-evals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function actionFetchExternalEvals(installationId: number): Promise<ExternalEvalListItem[]> {
  return serverBffFetch<ExternalEvalListItem[]>(`/api/v1/external-evals?installation_id=${installationId}`);
}

export async function actionFetchExternalEvalDetail(
  externalEvalId: number,
  installationId: number,
): Promise<ExternalEvalDetail> {
  return serverBffFetch<ExternalEvalDetail>(
    `/api/v1/external-evals/${externalEvalId}?installation_id=${installationId}`,
  );
}

export async function actionCancelExternalEval(
  externalEvalId: number,
  installationId: number,
): Promise<{ ok: boolean; external_eval_id: number; status: string }> {
  return serverBffFetch<{ ok: boolean; external_eval_id: number; status: string }>(
    `/api/v1/external-evals/${externalEvalId}/cancel`,
    {
      method: "POST",
      body: JSON.stringify({ installation_id: installationId }),
    },
  );
}
