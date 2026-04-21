import { NextResponse } from "next/server";

import { AUTH_COOKIE_TTL_SECONDS, AUTH_STATE_COOKIE_NAME } from "@/lib/auth/constants";
import { buildGitHubAuthorizeUrl } from "@/lib/auth/github";
import { createOAuthState } from "@/lib/auth/session";

function callbackUrl(requestUrl: string): string {
  const url = new URL("/api/v1/auth/callback", requestUrl);
  return url.toString();
}

export async function GET(request: Request): Promise<NextResponse> {
  if (!process.env.GITHUB_CLIENT_ID?.trim() || !process.env.GITHUB_CLIENT_SECRET?.trim()) {
    return NextResponse.json(
      {
        error:
          "GitHub OAuth is not configured. Copy apps/web/.env.example to apps/web/.env.local and set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET (Next.js reads env from apps/web, not the repo root).",
      },
      { status: 503 },
    );
  }

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
