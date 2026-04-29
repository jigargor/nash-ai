"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { actionGenerateRepoTemplate } from "@/app/actions/dashboard-api";

export function useGenerateRepoTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ owner, repo, installationId }: { owner: string; repo: string; installationId: number }) =>
      actionGenerateRepoTemplate(owner, repo, installationId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["repos"] });
    },
  });
}
