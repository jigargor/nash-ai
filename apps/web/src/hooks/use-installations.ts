"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchInstallations } from "@/lib/api/repos";

export function useInstallations() {
  return useQuery({
    queryKey: ["installations"],
    queryFn: fetchInstallations,
  });
}
