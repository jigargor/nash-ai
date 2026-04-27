"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchReview } from "@/lib/api/reviews";
import { isReviewInFlightStatus } from "@/lib/review-status";

export function useReview(reviewId: number, installationId?: number) {
  return useQuery({
    queryKey: ["review", reviewId, installationId ?? null],
    queryFn: () => fetchReview(reviewId, installationId),
    enabled: Number.isFinite(reviewId),
    refetchInterval: (query) => (isReviewInFlightStatus(query.state.data?.status) ? 3000 : false),
  });
}
