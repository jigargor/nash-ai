"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchModelsCatalog } from "@/lib/api/models";

export function useModelsCatalog() {
  return useQuery({
    queryKey: ["models-catalog"],
    queryFn: fetchModelsCatalog,
  });
}
