/** Top-level path prefixes that require a valid dashboard session (enforced in `proxy.ts`). */
export const DASHBOARD_ROUTE_PREFIXES = [
  "/dashboard",
  "/repos",
  "/reviews",
  "/code-tour",
  "/settings",
  "/models",
  "/evaluate-external",
] as const;

/** True when `pathname` is a protected prefix itself or a nested segment under it. */
export function isDashboardRoute(pathname: string): boolean {
  return DASHBOARD_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}
