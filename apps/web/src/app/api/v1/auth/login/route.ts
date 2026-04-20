import { NextResponse } from "next/server";

import { AUTH_COOKIE_TTL_SECONDS, AUTH_STATE_COOKIE_NAME } from "@/lib/auth/constants";
import { buildGitHubAuthorizeUrl } from "@/lib/auth/github";
import { createOAuthState } from "@/lib/auth/session";

function callbackUrl(requestUrl: string): string {
  const url = new URL("/api/v1/auth/callback", requestUrl);
  return url.toString();
}

export async function GET(request: Request): Promise<NextResponse> {
  const state = createOAuthState();
  const redirectUri = callbackUrl(request.url);
  const authorizeUrl = buildGitHubAuthorizeUrl(state, redirectUri);
  const response = NextResponse.redirect(authorizeUrl);
  response.cookies.set(AUTH_STATE_COOKIE_NAME, state, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: AUTH_COOKIE_TTL_SECONDS,
  });
  return response;
}
