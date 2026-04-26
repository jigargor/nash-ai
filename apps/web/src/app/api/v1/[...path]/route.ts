import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { parseSessionToken } from "@/lib/auth/session";
import { hydrateApiProxyEnvFromAncestors } from "@/lib/monorepo-env";

const DEFAULT_DEV_API = "http://localhost:8000";

/** Upstream fetch timeout so the browser does not hang on "Loading…" if Railway is unreachable. */
const UPSTREAM_TIMEOUT_MS = 25_000;

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
  const targetUrl = new URL(`/api/v1/${path.join("/")}${incomingUrl.search}`, apiBase);
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("Content-Type", contentType);
  if (accept) headers.set("Accept", accept);
  headers.set("X-Api-Key", apiAccessKey);

  try {
    return await fetch(targetUrl, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
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
