"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchReviews } from "@/app/actions/dashboard-api";
import type { ReviewListFilters } from "@/lib/api/reviews";
import { dashboardListMetricsQueryOptions } from "@/lib/query/dashboard-query-options";
import { isReviewInFlightStatus } from "@/lib/review-status";

export function useReviews(installationId?: number, filters?: ReviewListFilters) {
  return useQuery({
    queryKey: ["reviews", installationId ?? null, filters?.createdAfter ?? null, filters?.createdBefore ?? null],
    queryFn: () => actionFetchReviews(installationId, filters),
    ...dashboardListMetricsQueryOptions,
    refetchInterval: (query) => {
      const list = query.state.data;
      if (!list?.length) return false;
      return list.some((item) => isReviewInFlightStatus(item.status)) ? 4000 : false;
    },
  });
}
