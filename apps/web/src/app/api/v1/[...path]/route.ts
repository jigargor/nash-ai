import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { createDashboardUserToken } from "@/lib/auth/dashboard-token";
import { parseSessionToken } from "@/lib/auth/session";
import {
  apiErrorBody,
  makeApiError,
  normalizeApiErrorPayload,
  type NormalizedApiError,
} from "@/lib/api/error-normalize";

const DEFAULT_DEV_API = "http://localhost:8000";

/**
 * Without this, Vercel often ends the function at ~10s while we still wait on Railway
 * (`UPSTREAM_TIMEOUT_MS`), which surfaces as a blank 504 in the browser.
 * Raise toward 60 on Pro if Railway cold starts regularly exceed the upstream timeout.
 */
export const maxDuration = 30;

/** Upstream fetch timeout — must stay below `maxDuration` (leave headroom for cookie/session work). */
const UPSTREAM_TIMEOUT_MS = 25_000;
const MAX_PROXY_BODY_BYTES = 1024 * 1024; // 1 MiB
const REQUEST_ID_HEADER = "X-Request-ID";

/**
 * Railway (and most hosts) speak HTTPS on the public URL. If `API_URL` uses `http://`,
 * the upstream often responds with 302 → https. With `redirect: "manual"` that response
 * was forwarded to the browser, which then followed the redirect cross-origin and hit CORS.
 */
function normalizeUpstreamBaseUrl(base: string): string {
  const trimmed = base.trim();
  if (process.env.NODE_ENV !== "production") return trimmed;
  if (!trimmed.startsWith("http://")) return trimmed;
  if (trimmed.includes("localhost") || trimmed.includes("127.0.0.1")) return trimmed;
  return `https://${trimmed.slice("http://".length)}`;
}

export const runtime = "nodejs";

interface ApiProxyRouteContext {
  params: Promise<{
    path: string[];
  }>;
}

function errorResponse(error: NormalizedApiError): NextResponse {
  const headers = error.requestId ? { [REQUEST_ID_HEADER]: error.requestId } : undefined;
  return NextResponse.json(apiErrorBody(error), { status: error.status, headers });
}

async function normalizedUpstreamError(response: Response): Promise<NextResponse> {
  const text = await response.text();
  const normalized = normalizeApiErrorPayload(text, response.status);
  const requestId = response.headers.get(REQUEST_ID_HEADER) ?? normalized.requestId;
  return errorResponse({ ...normalized, requestId: requestId ?? undefined });
}

function isReviewRerunPath(path: string[]): boolean {
  return path.length === 3 && path[0] === "reviews" && path[2] === "rerun";
}

async function proxyApiRequest(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;
  const session = await parseSessionToken(token);
  if (!session) return errorResponse(makeApiError(401, "Unauthorized"));

  const apiAccessKey = process.env.API_ACCESS_KEY;
  if (!apiAccessKey) {
    return errorResponse(
      makeApiError(503, "API access key is not configured for the web proxy.", {
        code: "DEPENDENCY_WEB_PROXY_API_KEY_MISSING",
        family: "dependency",
        action: "contact_support",
      }),
    );
  }

  const apiBase =
    process.env.API_URL?.trim() || (process.env.NODE_ENV !== "production" ? DEFAULT_DEV_API : "");
  if (!apiBase) {
    return errorResponse(
      makeApiError(
        503,
        "API_URL is not set. Add your Railway API origin (e.g. https://nash-ai-api-production.up.railway.app) to Vercel env vars.",
        { code: "DEPENDENCY_WEB_PROXY_API_URL_MISSING", family: "dependency", action: "contact_support" },
      ),
    );
  }
  if (process.env.NODE_ENV === "production" && apiBase.includes("localhost")) {
    return errorResponse(
      makeApiError(
        503,
        "API_URL points at localhost in production. Set API_URL to your public Railway API URL in Vercel.",
        { code: "DEPENDENCY_WEB_PROXY_API_URL_INVALID", family: "dependency", action: "contact_support" },
      ),
    );
  }

  const { path } = await context.params;
  const cfClearanceCookie = cookieStore.get("cf_clearance")?.value;
  if (isReviewRerunPath(path) && !cfClearanceCookie) {
    return NextResponse.json(
      { detail: "Turnstile clearance cookie required to re-run reviews." },
      { status: 403 },
    );
  }
  const incomingUrl = new URL(request.url);
  const apiBaseNormalized = normalizeUpstreamBaseUrl(apiBase);
  const targetUrl = new URL(`/api/v1/${path.join("/")}${incomingUrl.search}`, apiBaseNormalized);
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("Content-Type", contentType);
  if (accept) headers.set("Accept", accept);
  let dashboardUserToken: string;
  try {
    dashboardUserToken = createDashboardUserToken(session.user);
  } catch {
    return errorResponse(
      makeApiError(503, "Dashboard user token auth is not configured.", {
        code: "DEPENDENCY_DASHBOARD_TOKEN_UNAVAILABLE",
        family: "dependency",
        action: "contact_support",
      }),
    );
  }
  headers.set("X-Api-Key", apiAccessKey);
  headers.set("X-Dashboard-User-Token", dashboardUserToken);
  headers.set("X-Usage-Service", "dashboard-bff");
  if (cfClearanceCookie) headers.set("X-CF-Clearance", cfClearanceCookie);

  let requestBody: ArrayBuffer | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const contentLengthHeader = request.headers.get("content-length");
    if (contentLengthHeader !== null) {
      const declaredLength = Number(contentLengthHeader);
      if (Number.isFinite(declaredLength) && declaredLength > MAX_PROXY_BODY_BYTES) {
        return errorResponse(makeApiError(413, `Request body exceeds ${MAX_PROXY_BODY_BYTES} byte limit.`));
      }
    }

    requestBody = await request.arrayBuffer();
    if (requestBody.byteLength > MAX_PROXY_BODY_BYTES) {
      return errorResponse(makeApiError(413, `Request body exceeds ${MAX_PROXY_BODY_BYTES} byte limit.`));
    }
  }

  try {
    const response = await fetch(targetUrl, {
      method: request.method,
      headers,
      body: requestBody,
      cache: "no-store",
      redirect: "follow",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    if (!response.ok) return await normalizedUpstreamError(response);
    return response;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upstream request failed";
    return errorResponse(
      makeApiError(504, `Backend request failed (${message}). Check API_URL and that the Railway API is running.`, {
        code: "UPSTREAM_API_TIMEOUT",
        family: "upstream",
        retryable: true,
        action: "retry",
      }),
    );
  }
}

export function GET(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  return proxyApiRequest(request, context);
}

export function POST(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  return proxyApiRequest(request, context);
}

export function PUT(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  return proxyApiRequest(request, context);
}

export function DELETE(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  return proxyApiRequest(request, context);
}

export function PATCH(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  return proxyApiRequest(request, context);
}
