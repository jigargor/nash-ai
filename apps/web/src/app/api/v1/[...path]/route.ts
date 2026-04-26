import { NextResponse } from "next/server";

import { hydrateApiProxyEnvFromAncestors } from "@/lib/monorepo-env";

const API_BASE = process.env.API_URL ?? "http://localhost:8000";

export const runtime = "nodejs";

interface ApiProxyRouteContext {
  params: Promise<{
    path: string[];
  }>;
}

async function proxyApiRequest(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  hydrateApiProxyEnvFromAncestors();
  const apiAccessKey = process.env.API_ACCESS_KEY;
  if (!apiAccessKey) {
    return NextResponse.json({ detail: "API access key is not configured for the web proxy." }, { status: 503 });
  }

  const { path } = await context.params;
  const incomingUrl = new URL(request.url);
  const apiBase = process.env.API_URL ?? API_BASE;
  const targetUrl = new URL(`/api/v1/${path.join("/")}${incomingUrl.search}`, apiBase);
  const headers = new Headers(request.headers);
  headers.set("X-Api-Key", apiAccessKey);
  headers.delete("host");

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
