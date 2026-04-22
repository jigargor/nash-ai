"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchOutcomeSummary } from "@/lib/api/reviews";

export function useOutcomeSummary(installationId?: number, repoFullName?: string) {
  return useQuery({
    queryKey: ["outcome-summary", installationId ?? null, repoFullName ?? null],
    queryFn: () => fetchOutcomeSummary(installationId, repoFullName),
  });
}
