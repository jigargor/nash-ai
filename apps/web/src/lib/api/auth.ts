import { apiFetch } from "@/lib/api/client";

export interface AuthMeResponse {
  authenticated: boolean;
  user?: {
    id: number;
    login: string;
  };
}

export function fetchCurrentUser() {
  return apiFetch<AuthMeResponse>("/api/v1/auth/me");
}
