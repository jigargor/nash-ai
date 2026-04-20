"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchReview } from "@/lib/api/reviews";

export function useReview(reviewId: number, installationId?: number) {
  return useQuery({
    queryKey: ["review", reviewId, installationId ?? null],
    queryFn: () => fetchReview(reviewId, installationId),
    enabled: Number.isFinite(reviewId),
  });
}
