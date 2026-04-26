import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { parseSessionToken } from "@/lib/auth/session";

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const pathname = request.nextUrl.pathname;
  const isDashboardRoute = pathname.startsWith("/dashboard") || pathname.startsWith("/repos");
  if (!isDashboardRoute) return NextResponse.next();

  const token = request.cookies.get(AUTH_COOKIE_NAME)?.value;
  const session = await parseSessionToken(token);
  // #region agent log
  fetch("http://127.0.0.1:7582/ingest/e6a057ab-47e4-4505-9884-d384fd412c69",{method:"POST",headers:{"Content-Type":"application/json","X-Debug-Session-Id":"7b2718"},body:JSON.stringify({sessionId:"7b2718",runId:"pre-fix-1",hypothesisId:"H2",location:"middleware.ts:15",message:"middleware_repo_route_seen",data:{pathname,search:request.nextUrl.search,hasSession:Boolean(session)},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
  if (session) return NextResponse.next();

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/dashboard/:path*", "/repos/:path*"],
};
