"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteUserKey, fetchUserKeys, upsertUserKey } from "@/lib/api/user-keys";

export function useUserKeys() {
  return useQuery({
    queryKey: ["user-keys"],
    queryFn: fetchUserKeys,
  });
}

export function useUpsertUserKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, api_key }: { provider: string; api_key: string }) =>
      upsertUserKey(provider, api_key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["user-keys"] }),
  });
}

export function useDeleteUserKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (provider: string) => deleteUserKey(provider),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["user-keys"] }),
  });
}
