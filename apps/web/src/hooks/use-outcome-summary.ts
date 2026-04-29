"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchOutcomeSummary } from "@/app/actions/dashboard-api";
import { dashboardListMetricsQueryOptions } from "@/lib/query/dashboard-query-options";

export function useOutcomeSummary(installationId?: number, repoFullName?: string) {
  return useQuery({
    queryKey: ["outcome-summary", installationId ?? null, repoFullName ?? null],
    queryFn: () => actionFetchOutcomeSummary(installationId, repoFullName),
    enabled: installationId !== undefined,
    ...dashboardListMetricsQueryOptions,
  });
}
