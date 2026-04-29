const API_BASE = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "";

/** Enforces dashboard data flow through Next.js `/api/v1/*` BFF in the browser (same-origin fetch). */
export function assertBrowserDashboardApiPath(path: string): void {
  if (typeof window === "undefined") return;
  if (path.startsWith("http://") || path.startsWith("https://")) {
    throw new Error(
      "Dashboard API calls must use same-origin `/api/v1/...` paths (Next.js BFF), not absolute upstream URLs.",
    );
  }
  if (!path.startsWith("/api/")) {
    throw new Error(
      `Dashboard API calls must target the Next.js BFF (path starting with "/api/"), got: ${path}`,
    );
  }
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function resolveApiRequestUrl(path: string): string {
  assertBrowserDashboardApiPath(path);
  // Dashboard data must hit the Next.js BFF (`/api/v1/*` routes) so cookies and `X-Api-Key` work.
  // Never merge NEXT_PUBLIC_API_BASE with `/api/…` or the browser CSP blocks cross-origin connects.
  if (path.startsWith("/api/")) return path;
  if (!API_BASE) return path;
  return path.startsWith("/") ? `${API_BASE}${path}` : `${API_BASE}/${path}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const requestUrl = resolveApiRequestUrl(path);
  const response = await fetch(requestUrl, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const maybeError = await response.text();
    throw new ApiError(response.status, maybeError || `API request failed: ${response.status}`);
  }
  const payload: unknown = await response.json();
  if (payload === null || payload === undefined) {
    throw new ApiError(response.status, "API returned an empty response payload.");
  }
  return payload as T;
}
