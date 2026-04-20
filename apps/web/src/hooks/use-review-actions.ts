"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { dismissFinding, rerunReview } from "@/lib/api/reviews";

export function useRerunReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reviewId: number) => rerunReview(reviewId),
    onSuccess: (_data, reviewId) => {
      void queryClient.invalidateQueries({ queryKey: ["review", reviewId] });
      void queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
  });
}

export function useDismissFinding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ reviewId, findingIndex }: { reviewId: number; findingIndex: number }) =>
      dismissFinding(reviewId, findingIndex),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["review", variables.reviewId] });
    },
  });
}
