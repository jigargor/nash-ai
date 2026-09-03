"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { actionFetchFindingLabels, actionLabelFinding } from "@/app/actions/dashboard-api";
import type { FindingLabelValue } from "@/lib/api/quality";

export function useFindingLabels(reviewId: number, enabled = true) {
  return useQuery({
    queryKey: ["finding-labels", reviewId],
    queryFn: () => actionFetchFindingLabels(reviewId),
    enabled: enabled && Number.isFinite(reviewId) && reviewId > 0,
    staleTime: 30_000,
  });
}

export function useLabelFinding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      reviewId,
      findingIndex,
      label,
      notes,
    }: {
      reviewId: number;
      findingIndex: number;
      label: FindingLabelValue;
      notes?: string | null;
    }) =>
      actionLabelFinding(reviewId, findingIndex, label, notes).then((result) => {
        if (!result.ok || !result.data) throw new Error(result.error?.message ?? "Unable to save finding label.");
        return result.data;
      }),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["finding-labels", variables.reviewId] });
    },
  });
}
