"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { actionCreateMissedIssue } from "@/app/actions/dashboard-api";
import type { MissedIssueCreateRequest } from "@/lib/api/quality";

export function useCreateMissedIssue() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: MissedIssueCreateRequest) =>
      actionCreateMissedIssue(body).then((result) => {
        if (!result.ok || !result.data) throw new Error(result.error?.message ?? "Unable to record missed issue.");
        return result.data;
      }),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["missed-issues", variables.review_id] });
    },
  });
}
