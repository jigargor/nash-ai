import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME, AUTH_COOKIE_TTL_SECONDS, AUTH_STATE_COOKIE_NAME } from "@/lib/auth/constants";
import { hydrateGithubOAuthEnvFromAncestors } from "@/lib/monorepo-env";
import { exchangeCodeForToken, getGitHubUser } from "@/lib/auth/github";
import { createSessionToken } from "@/lib/auth/session";

function appOrigin(requestUrl: string): string {
  const url = new URL(requestUrl);
  return `${url.protocol}//${url.host}`;
}

function callbackUrl(requestUrl: string): string {
  return `${appOrigin(requestUrl)}/api/v1/auth/callback`;
}

export async function GET(request: Request): Promise<NextResponse> {
  hydrateGithubOAuthEnvFromAncestors();
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const cookieStore = await cookies();
  const expectedState = cookieStore.get(AUTH_STATE_COOKIE_NAME)?.value;
  if (!code || !state || !expectedState || state !== expectedState)
    return NextResponse.redirect(new URL("/login?error=state_mismatch", request.url));

  try {
    const token = await exchangeCodeForToken(code, callbackUrl(request.url));
    const user = await getGitHubUser(token.access_token);
    const sessionToken = await createSessionToken({ id: user.id, login: user.login });

    // Upsert user record in the database — fire-and-forget, must not block login
    const apiBase = process.env.API_URL ?? "http://localhost:8000";
    fetch(`${apiBase}/api/v1/users/me`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Api-Key": process.env.API_ACCESS_KEY ?? "",
      },
      body: JSON.stringify({ github_id: user.id, login: user.login }),
    }).catch((err: unknown) => console.error("[auth/callback] user upsert failed (non-fatal)", err));

    const response = NextResponse.redirect(new URL("/dashboard", request.url));
    response.cookies.set(AUTH_COOKIE_NAME, sessionToken, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: AUTH_COOKIE_TTL_SECONDS,
    });
    response.cookies.delete(AUTH_STATE_COOKIE_NAME);
    return response;
  } catch (err) {
    console.error("[auth/callback] OAuth exchange failed", err);
    return NextResponse.redirect(new URL("/login?error=oauth_failed", request.url));
  }
}
