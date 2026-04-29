import { apiFetch } from "@/lib/api/client";

export interface AuthMeResponse {
  authenticated: boolean;
  user?: {
    id: number;
    login: string;
  };
}

export interface TermsStatusResponse {
  terms_version: string;
  accepted_terms_version: string | null;
  accepted_terms_at: string | null;
  requires_terms_acceptance: boolean;
}

export function fetchCurrentUser() {
  return apiFetch<AuthMeResponse>("/api/v1/auth/me");
}
