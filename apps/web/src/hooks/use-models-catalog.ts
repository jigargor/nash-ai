"use client";

import { useQuery } from "@tanstack/react-query";

import { actionFetchModelsCatalog } from "@/app/actions/dashboard-api";

export function useModelsCatalog() {
  return useQuery({
    queryKey: ["models-catalog"],
    queryFn: actionFetchModelsCatalog,
  });
}
