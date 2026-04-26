import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { parseSessionToken } from "@/lib/auth/session";

export async function GET(): Promise<NextResponse> {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;
  const session = await parseSessionToken(token);
  if (!session) return NextResponse.json({ authenticated: false }, { status: 401 });
  return NextResponse.json({
    authenticated: true,
    user: session.user,
  });
}
