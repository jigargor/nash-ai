/**
 * TanStack Query tuning for dashboard screens where data is not latency-critical.
 *
 * Recommendation: use a few minutes of staleness and avoid window-focus refetch storms;
 * keep narrow polling (or SSE) only while work is actively in progress (e.g. in-flight reviews).
 */
export const DASHBOARD_LIST_METRICS_STALE_MS = 5 * 60 * 1000;

export const dashboardListMetricsQueryOptions = {
  staleTime: DASHBOARD_LIST_METRICS_STALE_MS,
  refetchOnWindowFocus: false as const,
};
