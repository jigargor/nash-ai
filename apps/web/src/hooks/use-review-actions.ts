"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { dismissFinding, rerunReview } from "@/lib/api/reviews";

export function useRerunReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ reviewId, installationId }: { reviewId: number; installationId: number }) =>
      rerunReview(reviewId, installationId),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["review", variables.reviewId] });
      void queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
  });
}

export function useDismissFinding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      reviewId,
      findingIndex,
      installationId,
    }: {
      reviewId: number;
      findingIndex: number;
      installationId: number;
    }) => dismissFinding(reviewId, findingIndex, installationId),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["review", variables.reviewId] });
    },
  });
}
