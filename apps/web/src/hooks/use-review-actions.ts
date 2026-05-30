"use client";

import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { actionDismissFinding, actionForceRecoverReview, actionRerunReview } from "@/app/actions/dashboard-api";
import type { ReviewDetail, ReviewListItem } from "@/lib/api/reviews";

interface RerunContext {
  previousReview: ReviewDetail | undefined;
  reviewQueryKey: readonly [string, number, number];
  previousReviewLists: [QueryKey, ReviewListItem[] | undefined][];
}

export function useRerunReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      reviewId,
      installationId,
    }: {
      reviewId: number;
      installationId: number;
    }) => {
      return actionRerunReview(reviewId, installationId).then((result) => {
        if (!result.ok || !result.data) throw new Error(result.error?.message ?? "Unable to rerun review.");
        return result.data;
      });
    },
    onMutate: async ({ reviewId, installationId }) => {
      const reviewQueryKey = ["review", reviewId, installationId] as const;
      await queryClient.cancelQueries({ queryKey: reviewQueryKey });
      await queryClient.cancelQueries({ queryKey: ["reviews"] });
      const previousReview = queryClient.getQueryData<ReviewDetail>(reviewQueryKey);
      if (previousReview) {
        queryClient.setQueryData<ReviewDetail>(reviewQueryKey, { ...previousReview, status: "queued" });
      }
      const previousReviewLists = queryClient.getQueriesData<ReviewListItem[]>({ queryKey: ["reviews"] });
      queryClient.setQueriesData<ReviewListItem[]>({ queryKey: ["reviews"] }, (old) => {
        if (!old) return old;
        return old.map((r) => (r.id === reviewId ? { ...r, status: "queued" } : r));
      });
      return { previousReview, reviewQueryKey, previousReviewLists } satisfies RerunContext;
    },
    onError: (_err, _variables, context) => {
      if (!context) return;
      if (context.previousReview) {
        queryClient.setQueryData(context.reviewQueryKey, context.previousReview);
      }
      for (const [key, data] of context.previousReviewLists) {
        queryClient.setQueryData(key, data);
      }
    },
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["review", variables.reviewId, variables.installationId] });
      void queryClient.invalidateQueries({ queryKey: ["review-model-audits", variables.reviewId, variables.installationId] });
      void queryClient.invalidateQueries({ queryKey: ["reviews", variables.installationId] });
      void queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
  });
}

export function useForceRecoverReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      reviewId,
      installationId,
      action,
    }: {
      reviewId: number;
      installationId: number;
      action: "mark_failed" | "force_requeue";
    }) => {
      return actionForceRecoverReview(reviewId, installationId, action).then((result) => {
        if (!result.ok || !result.data) throw new Error(result.error?.message ?? "Unable to perform recovery action.");
        return result.data;
      });
    },
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["review", variables.reviewId, variables.installationId] });
      void queryClient.invalidateQueries({ queryKey: ["review-model-audits", variables.reviewId, variables.installationId] });
      void queryClient.invalidateQueries({ queryKey: ["reviews", variables.installationId] });
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
    }) => actionDismissFinding(reviewId, findingIndex, installationId),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["review", variables.reviewId, variables.installationId] });
      void queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
  });
}
