import { apiFetch } from "@/lib/api/client";

export interface RepoInstallation {
  installation_id: number;
  account_login: string;
  account_type: string;
}

export function fetchInstallations() {
  return apiFetch<RepoInstallation[]>("/api/v1/installations");
}
