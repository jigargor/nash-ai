"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchReviewOutcomes } from "@/lib/api/reviews";

export function useReviewOutcomes(reviewId: number, installationId?: number) {
  return useQuery({
    queryKey: ["review-outcomes", reviewId, installationId ?? null],
    queryFn: () => fetchReviewOutcomes(reviewId, installationId),
    enabled: Number.isFinite(reviewId),
  });
}
