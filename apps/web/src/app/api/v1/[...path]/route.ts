import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { parseSessionToken } from "@/lib/auth/session";
import { hydrateApiProxyEnvFromAncestors } from "@/lib/monorepo-env";

const API_BASE = process.env.API_URL ?? "http://localhost:8000";

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

  const { path } = await context.params;
  const incomingUrl = new URL(request.url);
  const apiBase = process.env.API_URL ?? API_BASE;
  const targetUrl = new URL(`/api/v1/${path.join("/")}${incomingUrl.search}`, apiBase);
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("Content-Type", contentType);
  if (accept) headers.set("Accept", accept);
  headers.set("X-Api-Key", apiAccessKey);

  return fetch(targetUrl, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
    cache: "no-store",
    redirect: "manual",
  });
}

export function GET(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  return proxyApiRequest(request, context);
}

export function POST(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  return proxyApiRequest(request, context);
}
