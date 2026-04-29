"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchCodeReviewConfig } from "@/app/actions/dashboard-api";

export function useCodeReviewConfig(
  owner: string | null,
  repo: string | null,
  installationId: number | null,
) {
  return useQuery({
    queryKey: ["codereview-config", owner, repo, installationId],
    queryFn: () => actionFetchCodeReviewConfig(owner!, repo!, installationId!),
    enabled: owner !== null && repo !== null && installationId !== null,
  });
}
