import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { parseSessionToken } from "@/lib/auth/session";

export default async function Home() {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;
  const session = await parseSessionToken(token);
  if (session) redirect("/dashboard");
  redirect("/login");
}
