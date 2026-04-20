"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchReviews } from "@/lib/api/reviews";

export function useReviews(installationId?: number) {
  return useQuery({
    queryKey: ["reviews", installationId ?? null],
    queryFn: () => fetchReviews(installationId),
  });
}
