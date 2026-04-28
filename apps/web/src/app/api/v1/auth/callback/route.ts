import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import {
  AUTH_COOKIE_NAME,
  AUTH_COOKIE_TTL_SECONDS,
  AUTH_PKCE_VERIFIER_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
} from "@/lib/auth/constants";
import { createDashboardUserToken } from "@/lib/auth/dashboard-token";
import { exchangeCodeForToken, getGitHubUser, listGitHubUserInstallations } from "@/lib/auth/github";
import { createSessionToken } from "@/lib/auth/session";

function appOrigin(requestUrl: string): string {
  const url = new URL(requestUrl);
  return `${url.protocol}//${url.host}`;
}

function callbackUrl(requestUrl: string): string {
  return `${appOrigin(requestUrl)}/api/v1/auth/callback`;
}

function redirectToLoginWithError(error: string, requestUrl: string): NextResponse {
  const response = NextResponse.redirect(new URL(`/login?error=${error}`, requestUrl));
  response.cookies.delete(AUTH_STATE_COOKIE_NAME);
  response.cookies.delete(AUTH_PKCE_VERIFIER_COOKIE_NAME);
  return response;
}

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const cookieStore = await cookies();
  const expectedState = cookieStore.get(AUTH_STATE_COOKIE_NAME)?.value;
  const codeVerifier = cookieStore.get(AUTH_PKCE_VERIFIER_COOKIE_NAME)?.value;
  if (!code || !state || !expectedState || state !== expectedState) {
    return redirectToLoginWithError("state_mismatch", request.url);
  }
  if (!codeVerifier) return redirectToLoginWithError("pkce_mismatch", request.url);

  try {
    const token = await exchangeCodeForToken(code, callbackUrl(request.url), codeVerifier);
    const [user, installations] = await Promise.all([
      getGitHubUser(token.access_token),
      listGitHubUserInstallations(token.access_token).catch(() => []),
    ]);
    const sessionToken = await createSessionToken({ id: user.id, login: user.login });
    const dashboardUserToken = createDashboardUserToken({ id: user.id, login: user.login });

    // Upsert user record in the database — fire-and-forget, must not block login
    const apiBase = process.env.API_URL ?? "http://localhost:8000";
    fetch(`${apiBase}/api/v1/users/me`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Api-Key": process.env.API_ACCESS_KEY ?? "",
        "X-Dashboard-User-Token": dashboardUserToken,
      },
      body: JSON.stringify({ login: user.login, oauth_token: token.access_token }),
    }).catch((err: unknown) => console.error("[auth/callback] user upsert failed (non-fatal)", err));
    fetch(`${apiBase}/api/v1/users/me/installations-sync`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Api-Key": process.env.API_ACCESS_KEY ?? "",
        "X-Dashboard-User-Token": dashboardUserToken,
      },
      body: JSON.stringify({
        installations: installations.map((installation) => ({
          installation_id: installation.id,
          account_login: installation.account?.login ?? `installation-${installation.id}`,
          account_type: installation.account?.type ?? "Unknown",
        })),
      }),
    }).catch((err: unknown) =>
      console.error("[auth/callback] installation sync failed (non-fatal)", err),
    );

    const response = NextResponse.redirect(new URL("/dashboard", request.url));
    response.cookies.set(AUTH_COOKIE_NAME, sessionToken, {
      httpOnly: true,
      sameSite: "lax",
      secure: true, // required by __Host- prefix; browsers accept this on localhost
      path: "/",
      maxAge: AUTH_COOKIE_TTL_SECONDS,
    });
    response.cookies.delete(AUTH_STATE_COOKIE_NAME);
    response.cookies.delete(AUTH_PKCE_VERIFIER_COOKIE_NAME);
    return response;
  } catch (err) {
    console.error("[auth/callback] OAuth exchange failed", err);
    return redirectToLoginWithError("oauth_failed", request.url);
  }
}
