"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { actionDeleteUserKey, actionFetchUserKeys, actionUpsertUserKey } from "@/app/actions/dashboard-api";

export function useUserKeys() {
  return useQuery({
    queryKey: ["user-keys"],
    queryFn: actionFetchUserKeys,
  });
}

export function useUpsertUserKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, api_key }: { provider: string; api_key: string }) =>
      actionUpsertUserKey(provider, api_key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["user-keys"] }),
  });
}

export function useDeleteUserKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (provider: string) => actionDeleteUserKey(provider),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["user-keys"] }),
  });
}
