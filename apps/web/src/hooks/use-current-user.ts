"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchCurrentUser } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

export function useCurrentUser() {
  return useQuery({
    queryKey: ["current-user"],
    queryFn: async () => {
      try {
        return await fetchCurrentUser();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return { authenticated: false } as const;
        throw error;
      }
    },
    staleTime: 60_000,
  });
}
