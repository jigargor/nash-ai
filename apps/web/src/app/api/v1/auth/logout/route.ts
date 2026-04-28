import { NextResponse } from "next/server";

import {
  AUTH_COOKIE_NAME,
  AUTH_PKCE_VERIFIER_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
} from "@/lib/auth/constants";

export async function GET(request: Request): Promise<NextResponse> {
  const response = NextResponse.redirect(new URL("/login", request.url));
  response.cookies.delete(AUTH_COOKIE_NAME);
  response.cookies.delete(AUTH_STATE_COOKIE_NAME);
  response.cookies.delete(AUTH_PKCE_VERIFIER_COOKIE_NAME);
  return response;
}
