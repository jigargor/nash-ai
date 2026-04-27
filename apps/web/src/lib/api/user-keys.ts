import { apiFetch } from "@/lib/api/client";

export interface KeyStatus {
  provider: string;
  has_key: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_used_at: string | null;
}

export function fetchUserKeys() {
  return apiFetch<KeyStatus[]>("/api/v1/users/me/keys");
}

export function upsertUserKey(provider: string, api_key: string) {
  return apiFetch<{ detail: string }>(`/api/v1/users/me/keys/${provider}`, {
    method: "PUT",
    body: JSON.stringify({ api_key }),
  });
}

export function deleteUserKey(provider: string) {
  return apiFetch<{ detail: string }>(`/api/v1/users/me/keys/${provider}`, {
    method: "DELETE",
  });
}
