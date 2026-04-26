"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchReviewModelAudits } from "@/lib/api/reviews";

export function useReviewModelAudits(reviewId: number, installationId?: number) {
  return useQuery({
    queryKey: ["review-model-audits", reviewId, installationId ?? null],
    queryFn: () => fetchReviewModelAudits(reviewId, installationId),
    enabled: Number.isFinite(reviewId),
  });
}
