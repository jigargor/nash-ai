"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchUsageSummary } from "@/lib/api/usage";

export function useUsageSummary(installationId?: number) {
  return useQuery({
    queryKey: ["usage-summary", installationId ?? null],
    queryFn: () => fetchUsageSummary(installationId as number),
    enabled: typeof installationId === "number" && installationId > 0,
  });
}

