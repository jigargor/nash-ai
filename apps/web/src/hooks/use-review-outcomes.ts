"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchReviewOutcomes } from "@/app/actions/dashboard-api";

export function useReviewOutcomes(reviewId: number, installationId?: number) {
  return useQuery({
    queryKey: ["review-outcomes", reviewId, installationId ?? null],
    queryFn: () => actionFetchReviewOutcomes(reviewId, installationId),
    enabled: Number.isFinite(reviewId),
  });
}
