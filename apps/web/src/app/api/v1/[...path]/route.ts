import { NextResponse } from "next/server";

const API_BASE = process.env.API_URL ?? "http://localhost:8000";

interface ApiProxyRouteContext {
  params: Promise<{
    path: string[];
  }>;
}

async function proxyApiRequest(request: Request, context: ApiProxyRouteContext): Promise<Response> {
  const apiAccessKey = process.env.API_ACCESS_KEY;
  if (!apiAccessKey) {
    return NextResponse.json({ detail: "API access key is not configured for the web proxy." }, { status: 503 });
  }

  const { path } = await context.params;
  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(`/api/v1/${path.join("/")}${incomingUrl.search}`, API_BASE);
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
