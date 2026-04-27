import { createHmac } from "node:crypto";

interface DashboardTokenUser {
  id: number;
  login: string;
}

function base64UrlEncode(value: string): string {
  return Buffer.from(value).toString("base64url");
}

function dashboardTokenSecret(): string {
  const secret = process.env.DASHBOARD_USER_JWT_SECRET?.trim();
  if (secret) return secret;
  throw new Error("DASHBOARD_USER_JWT_SECRET is not configured");
}

function dashboardTokenAudience(): string {
  return process.env.DASHBOARD_USER_JWT_AUDIENCE?.trim() || "dashboard-api";
}

function dashboardTokenIssuer(): string {
  return process.env.DASHBOARD_USER_JWT_ISSUER?.trim() || "nash-web-dashboard";
}

export function createDashboardUserToken(user: DashboardTokenUser): string {
  const nowSeconds = Math.floor(Date.now() / 1000);
  const payload = {
    sub: String(user.id),
    login: user.login,
    aud: dashboardTokenAudience(),
    iss: dashboardTokenIssuer(),
    iat: nowSeconds,
    exp: nowSeconds + 5 * 60,
  };
  const encodedHeader = base64UrlEncode(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const encodedPayload = base64UrlEncode(JSON.stringify(payload));
  const signedPayload = `${encodedHeader}.${encodedPayload}`;
  const signature = createHmac("sha256", dashboardTokenSecret()).update(signedPayload).digest("base64url");
  return `${signedPayload}.${signature}`;
}
