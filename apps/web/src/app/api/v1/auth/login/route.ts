import { NextResponse } from "next/server";

import {
  AUTH_COOKIE_TTL_SECONDS,
  AUTH_PKCE_VERIFIER_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
} from "@/lib/auth/constants";
import { buildGitHubAuthorizeUrl } from "@/lib/auth/github";
import { createOAuthState, createPkceCodeVerifier, derivePkceCodeChallenge } from "@/lib/auth/session";

const TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

interface TurnstileVerifyResponse {
  success?: boolean;
}

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

function redirectToLoginWithError(requestUrl: string, error: string): NextResponse {
  return NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(error)}`, requestUrl), 303);
}

function loginIpAddress(request: Request): string | null {
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) {
    const first = forwardedFor.split(",")[0]?.trim();
    if (first) return first;
  }
  return request.headers.get("cf-connecting-ip");
}

async function verifyTurnstileToken(request: Request, token: string | null): Promise<boolean> {
  const turnstileSecretKey = process.env.TURNSTILE_SECRET_KEY?.trim();
  if (!turnstileSecretKey) return true;
  if (!token) return false;
  const payload = new URLSearchParams({
    secret: turnstileSecretKey,
    response: token,
  });
  const remoteIp = loginIpAddress(request);
  if (remoteIp) payload.set("remoteip", remoteIp);

  try {
    const response = await fetch(TURNSTILE_SITEVERIFY_URL, {
      method: "POST",
      body: payload,
      cache: "no-store",
    });
    if (!response.ok) return false;
    const body = (await response.json()) as TurnstileVerifyResponse;
    return body.success === true;
  } catch {
    return false;
  }
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
  return NextResponse.redirect(new URL("/login", request.url), 303);
}

export async function POST(request: Request): Promise<NextResponse> {
  if (!process.env.GITHUB_CLIENT_ID?.trim() || !process.env.GITHUB_CLIENT_SECRET?.trim()) {
    return oauthNotConfiguredResponse();
  }

  const formData = await request.formData();
  const turnstileToken = formData.get("turnstile_token");
  const isValidTurnstileToken = await verifyTurnstileToken(
    request,
    typeof turnstileToken === "string" ? turnstileToken : null,
  );
  if (!isValidTurnstileToken) return redirectToLoginWithError(request.url, "turnstile_failed");

  return await redirectToGitHub(request, 303);
}
