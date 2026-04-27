"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import type { ReviewDetail } from "@/lib/api/reviews";
import { fetchReviewModelAudits } from "@/lib/api/reviews";
import { isReviewInFlightStatus } from "@/lib/review-status";

export function useReviewModelAudits(reviewId: number, installationId?: number) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["review-model-audits", reviewId, installationId ?? null],
    queryFn: () => fetchReviewModelAudits(reviewId, installationId),
    enabled: Number.isFinite(reviewId),
    refetchInterval: () => {
      const review = queryClient.getQueryData<ReviewDetail>(["review", reviewId, installationId ?? null]);
      return isReviewInFlightStatus(review?.status) ? 4000 : false;
    },
  });
}
