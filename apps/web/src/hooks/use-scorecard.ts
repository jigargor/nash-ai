"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchCostPerFinding, actionFetchScorecard } from "@/app/actions/dashboard-api";
import { dashboardListMetricsQueryOptions } from "@/lib/query/dashboard-query-options";

export function useScorecard(installationId?: number, repoFullName?: string, days = 14) {
  return useQuery({
    queryKey: ["scorecard", installationId ?? null, repoFullName ?? null, days],
    queryFn: () => actionFetchScorecard(installationId as number, repoFullName, days),
    enabled: typeof installationId === "number" && installationId > 0,
    ...dashboardListMetricsQueryOptions,
  });
}

export function useCostPerFinding(installationId?: number) {
  return useQuery({
    queryKey: ["cost-per-finding", installationId ?? null],
    queryFn: () => actionFetchCostPerFinding(installationId as number),
    enabled: typeof installationId === "number" && installationId > 0,
    ...dashboardListMetricsQueryOptions,
  });
}
