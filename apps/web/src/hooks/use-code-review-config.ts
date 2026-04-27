"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchCodeReviewConfig } from "@/lib/api/repos";

export function useCodeReviewConfig(
  owner: string | null,
  repo: string | null,
  installationId: number | null,
) {
  return useQuery({
    queryKey: ["codereview-config", owner, repo, installationId],
    queryFn: () => fetchCodeReviewConfig(owner!, repo!, installationId!),
    enabled: owner !== null && repo !== null && installationId !== null,
  });
}
