"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchUsageSummary } from "@/app/actions/dashboard-api";
import { dashboardListMetricsQueryOptions } from "@/lib/query/dashboard-query-options";

export function useUsageSummary(installationId?: number) {
  return useQuery({
    queryKey: ["usage-summary", installationId ?? null],
    queryFn: () => actionFetchUsageSummary(installationId as number),
    enabled: typeof installationId === "number" && installationId > 0,
    ...dashboardListMetricsQueryOptions,
    refetchInterval: 120_000,
  });
}

