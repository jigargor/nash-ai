"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchInstallations } from "@/app/actions/dashboard-api";
import { dashboardListMetricsQueryOptions } from "@/lib/query/dashboard-query-options";

export function useInstallations() {
  return useQuery({
    queryKey: ["installations"],
    queryFn: actionFetchInstallations,
    ...dashboardListMetricsQueryOptions,
  });
}
