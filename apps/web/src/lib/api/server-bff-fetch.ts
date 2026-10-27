import "server-only";

import { cookies, headers } from "next/headers";

import { ApiError } from "@/lib/api/client";
import { resolveBffBaseUrl } from "@/lib/api/bff-base-url";
import { normalizeApiErrorPayload } from "@/lib/api/error-normalize";

/**
 * Server-only JSON fetch to the Next.js `/api/v1/*` BFF with the caller's cookies.
 * Keeps dashboard REST reads and mutations off the browser's fetch path (Server Actions invoke this).
 */
export async function serverBffFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!path.startsWith("/api/")) {
    throw new Error(`serverBffFetch path must start with /api/: ${path}`);
  }
  const hdrs = await headers();
  // Never trust x-forwarded-host / x-forwarded-proto: they are client-controllable and would let a
  // caller redirect this cookie-bearing loopback request to an arbitrary origin.
  const url = `${resolveBffBaseUrl(hdrs.get("host"), process.env)}${path}`;

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
    throw new ApiError(
      response.status,
      normalizeApiErrorPayload(maybeError || `API request failed: ${response.status}`, response.status),
    );
  }
  const payload: unknown = await response.json();
  if (payload === null || payload === undefined) {
    throw new ApiError(response.status, "API returned an empty response payload.");
  }
  return payload as T;
}
