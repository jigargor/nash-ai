import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { createDashboardUserToken } from "@/lib/auth/dashboard-token";
import { parseSessionToken } from "@/lib/auth/session";
import { hydrateApiProxyEnvFromAncestors } from "@/lib/monorepo-env";

const DEFAULT_DEV_API = "http://localhost:8000";

/**
 * Without this, Vercel often ends the function at ~10s while we still wait on Railway
 * (`UPSTREAM_TIMEOUT_MS`), which surfaces as a blank 504 in the browser.
 * Raise toward 60 on Pro if Railway cold starts regularly exceed the upstream timeout.
 */
export const maxDuration = 30;

/** Upstream fetch timeout — must stay below `maxDuration` (leave headroom for cookie/session work). */
const UPSTREAM_TIMEOUT_MS = 25_000;

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

async function proxyApiRequest(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;
  const session = await parseSessionToken(token);
  if (!session) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  hydrateApiProxyEnvFromAncestors();
  const apiAccessKey = process.env.API_ACCESS_KEY;
  if (!apiAccessKey) {
    return NextResponse.json({ detail: "API access key is not configured for the web proxy." }, { status: 503 });
  }

  const apiBase =
    process.env.API_URL?.trim() || (process.env.NODE_ENV !== "production" ? DEFAULT_DEV_API : "");
  if (!apiBase) {
    return NextResponse.json(
      {
        detail:
          "API_URL is not set. Add your Railway API origin (e.g. https://nash-ai-api-production.up.railway.app) to Vercel env vars.",
      },
      { status: 503 },
    );
  }
  if (process.env.NODE_ENV === "production" && apiBase.includes("localhost")) {
    return NextResponse.json(
      {
        detail:
          "API_URL points at localhost in production. Set API_URL to your public Railway API URL in Vercel.",
      },
      { status: 503 },
    );
  }

  const { path } = await context.params;
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
    return NextResponse.json({ detail: "Dashboard user token auth is not configured." }, { status: 503 });
  }
  headers.set("X-Api-Key", apiAccessKey);
  headers.set("X-Dashboard-User-Token", dashboardUserToken);

  try {
    return await fetch(targetUrl, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "follow",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upstream request failed";
    return NextResponse.json(
      { detail: `Backend request failed (${message}). Check API_URL and that the Railway API is running.` },
      { status: 504 },
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
