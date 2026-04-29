"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { actionAcceptTerms, actionFetchTermsStatus } from "@/app/actions/dashboard-api";

export function useTermsStatus() {
  return useQuery({
    queryKey: ["terms-status"],
    queryFn: actionFetchTermsStatus,
    staleTime: 60_000,
  });
}

export function useAcceptTerms() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: actionAcceptTerms,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["terms-status"] });
    },
  });
}
