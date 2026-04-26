"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchRepos } from "@/lib/api/repos";

export function useRepos(installationId?: number) {
  return useQuery({
    queryKey: ["repos", installationId ?? null],
    queryFn: () => fetchRepos(installationId),
  });
}
