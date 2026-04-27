"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchReviews } from "@/lib/api/reviews";
import { isReviewInFlightStatus } from "@/lib/review-status";

export function useReviews(installationId?: number) {
  return useQuery({
    queryKey: ["reviews", installationId ?? null],
    queryFn: () => fetchReviews(installationId),
    refetchInterval: (query) => {
      const list = query.state.data;
      if (!list?.length) return false;
      return list.some((item) => isReviewInFlightStatus(item.status)) ? 4000 : false;
    },
  });
}
