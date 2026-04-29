"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchRepos } from "@/app/actions/dashboard-api";

export function useRepos(installationId?: number) {
  return useQuery({
    queryKey: ["repos", installationId ?? null],
    queryFn: () => actionFetchRepos(installationId),
  });
}
