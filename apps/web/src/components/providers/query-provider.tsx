"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { dashboardListMetricsQueryOptions } from "@/lib/query/dashboard-query-options";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: dashboardListMetricsQueryOptions.staleTime,
            refetchOnWindowFocus: dashboardListMetricsQueryOptions.refetchOnWindowFocus,
          },
        },
      }),
  );
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
