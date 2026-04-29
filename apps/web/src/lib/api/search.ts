import { apiFetch } from "@/lib/api/client";

export interface SearchResultItem {
  type: "repo" | "pr";
  label: string;
  href: string;
  subtitle: string | null;
}

export function fetchDashboardSearch(query: string): Promise<SearchResultItem[]> {
  const params = new URLSearchParams();
  params.set("q", query);
  return apiFetch<SearchResultItem[]>(`/api/v1/search?${params.toString()}`);
}
