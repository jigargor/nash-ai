"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchDashboardSearch } from "@/lib/api/search";

export function useDashboardSearch(query: string) {
  const normalized = query.trim();
  return useQuery({
    queryKey: ["dashboard-search", normalized],
    queryFn: () => fetchDashboardSearch(normalized),
    enabled: normalized.length >= 2,
    staleTime: 15_000,
  });
}
