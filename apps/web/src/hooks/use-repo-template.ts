"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { generateRepoTemplate } from "@/lib/api/repos";

export function useGenerateRepoTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ owner, repo, installationId }: { owner: string; repo: string; installationId: number }) =>
      generateRepoTemplate(owner, repo, installationId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["repos"] });
    },
  });
}
