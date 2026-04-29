import { NextResponse } from "next/server";

import {
  AUTH_COOKIE_TTL_SECONDS,
  AUTH_PKCE_VERIFIER_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
} from "@/lib/auth/constants";
import { buildGitHubAuthorizeUrl } from "@/lib/auth/github";
import { createOAuthState, createPkceCodeVerifier, derivePkceCodeChallenge } from "@/lib/auth/session";

function callbackUrl(requestUrl: string): string {
  const url = new URL("/api/v1/auth/callback", requestUrl);
  return url.toString();
}

function oauthNotConfiguredResponse(): NextResponse {
  return NextResponse.json(
    {
      error:
        "GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in repo-root or apps/web `.env.local`, then restart `next dev`.",
    },
    { status: 503 },
  );
}

async function redirectToGitHub(request: Request, statusCode?: number): Promise<NextResponse> {
  const state = createOAuthState();
  const codeVerifier = createPkceCodeVerifier();
  const codeChallenge = await derivePkceCodeChallenge(codeVerifier);
  const redirectUri = callbackUrl(request.url);
  const authorizeUrl = buildGitHubAuthorizeUrl(state, redirectUri, codeChallenge);
  const response = statusCode
    ? NextResponse.redirect(authorizeUrl, statusCode)
    : NextResponse.redirect(authorizeUrl);
  response.cookies.set(AUTH_STATE_COOKIE_NAME, state, {
    httpOnly: true,
    sameSite: "lax",
    secure: true,
    path: "/",
    maxAge: AUTH_COOKIE_TTL_SECONDS,
  });
  response.cookies.set(AUTH_PKCE_VERIFIER_COOKIE_NAME, codeVerifier, {
    httpOnly: true,
    sameSite: "lax",
    secure: true,
    path: "/",
    maxAge: AUTH_COOKIE_TTL_SECONDS,
  });
  return response;
}

export async function GET(request: Request): Promise<NextResponse> {
  if (!process.env.GITHUB_CLIENT_ID?.trim() || !process.env.GITHUB_CLIENT_SECRET?.trim()) {
    return oauthNotConfiguredResponse();
  }

  return await redirectToGitHub(request);
}

export async function POST(request: Request): Promise<NextResponse> {
  if (!process.env.GITHUB_CLIENT_ID?.trim() || !process.env.GITHUB_CLIENT_SECRET?.trim()) {
    return oauthNotConfiguredResponse();
  }

  await request.formData();
  return await redirectToGitHub(request, 303);
}
