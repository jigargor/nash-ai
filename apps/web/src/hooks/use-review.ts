"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchReview } from "@/lib/api/reviews";
import { isReviewInFlightStatus } from "@/lib/review-status";

interface UseReviewOptions {
  enabled?: boolean;
}

export function useReview(reviewId: number, installationId?: number, options?: UseReviewOptions) {
  return useQuery({
    queryKey: ["review", reviewId, installationId ?? null],
    // Browser fetch to the same-origin BFF: polling avoids a Server Action + loopback hop per tick.
    queryFn: () => fetchReview(reviewId, installationId),
    enabled: Number.isFinite(reviewId) && (options?.enabled ?? true),
    refetchInterval: (query) => (isReviewInFlightStatus(query.state.data?.status) ? 3000 : false),
  });
}
