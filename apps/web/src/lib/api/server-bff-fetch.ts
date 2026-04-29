import "server-only";

import { cookies, headers } from "next/headers";

import { ApiError } from "@/lib/api/client";

/**
 * Server-only JSON fetch to the Next.js `/api/v1/*` BFF with the caller's cookies.
 * Keeps dashboard REST reads and mutations off the browser's fetch path (Server Actions invoke this).
 */
export async function serverBffFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!path.startsWith("/api/")) {
    throw new Error(`serverBffFetch path must start with /api/: ${path}`);
  }
  const hdrs = await headers();
  const host = hdrs.get("x-forwarded-host") ?? hdrs.get("host") ?? "localhost:3000";
  const forwardedProto = hdrs.get("x-forwarded-proto");
  const proto =
    forwardedProto ??
    (process.env.VERCEL === "1" || process.env.NODE_ENV === "production" ? "https" : "http");
  const url = `${proto}://${host}${path}`;

  const cookieStore = await cookies();
  const cookieHeader = cookieStore.getAll().map((c) => `${c.name}=${c.value}`).join("; ");

  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
      Cookie: cookieHeader,
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
