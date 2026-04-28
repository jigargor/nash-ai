import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { parseSessionToken } from "@/lib/auth/session";

// ---------------------------------------------------------------------------
// Rate limiting (Upstash Redis — fail-open when not configured)
// Set UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN in Vercel to enable.
// ---------------------------------------------------------------------------

async function checkRateLimit(request: NextRequest): Promise<NextResponse | null> {
  const upstashUrl = process.env.UPSTASH_REDIS_REST_URL;
  const upstashToken = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!upstashUrl || !upstashToken) return null; // not configured — skip

  const { Ratelimit } = await import("@upstash/ratelimit");
  const { Redis } = await import("@upstash/redis");

  const ratelimit = new Ratelimit({
    redis: new Redis({ url: upstashUrl, token: upstashToken }),
    // 10 requests per minute per IP on auth routes
    limiter: Ratelimit.slidingWindow(10, "1 m"),
    analytics: false,
  });

  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    request.headers.get("x-real-ip") ??
    "anonymous";

  const { success, limit, remaining, reset } = await ratelimit.limit(`auth:${ip}`);
  if (success) return null;

  return NextResponse.json(
    { error: "Too many requests. Please try again later." },
    {
      status: 429,
      headers: {
        "Retry-After": String(Math.ceil((reset - Date.now()) / 1000)),
        "X-RateLimit-Limit": String(limit),
        "X-RateLimit-Remaining": String(remaining),
      },
    },
  );
}

// ---------------------------------------------------------------------------
// Proxy
// ---------------------------------------------------------------------------

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const pathname = request.nextUrl.pathname;

  // Rate-limit all auth endpoints
  if (pathname.startsWith("/api/v1/auth/")) {
    const limited = await checkRateLimit(request);
    if (limited) return limited;
  }

  // Protect dashboard routes — redirect to login if session is invalid
  const isDashboardRoute =
    pathname.startsWith("/dashboard") ||
    pathname.startsWith("/repos") ||
    pathname.startsWith("/reviews") ||
    pathname.startsWith("/settings");
  if (!isDashboardRoute) return NextResponse.next();

  const token = request.cookies.get(AUTH_COOKIE_NAME)?.value;
  const session = await parseSessionToken(token);
  if (session) return NextResponse.next();

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    "/api/v1/auth/:path*",
    "/dashboard/:path*",
    "/repos/:path*",
    "/reviews/:path*",
    "/settings/:path*",
  ],
};
