import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import { AUTH_COOKIE_TTL_SECONDS } from "@/lib/auth/constants";

export interface SessionUser {
  id: number;
  login: string;
}

export interface SessionPayload {
  sub: string;
  user: SessionUser;
  exp: number;
}

function getSessionSecret(): string {
  return process.env.AUTH_SESSION_SECRET ?? "dev-insecure-session-secret";
}

function toBase64Url(value: string): string {
  return Buffer.from(value, "utf-8").toString("base64url");
}

function fromBase64Url(value: string): string {
  return Buffer.from(value, "base64url").toString("utf-8");
}

function signValue(value: string): string {
  const secret = getSessionSecret();
  return createHmac("sha256", secret).update(value).digest("base64url");
}

export function createOAuthState(): string {
  return randomBytes(24).toString("base64url");
}

export function createSessionToken(user: SessionUser): string {
  const payload: SessionPayload = {
    sub: String(user.id),
    user,
    exp: Math.floor(Date.now() / 1000) + AUTH_COOKIE_TTL_SECONDS,
  };
  const encoded = toBase64Url(JSON.stringify(payload));
  const signature = signValue(encoded);
  return `${encoded}.${signature}`;
}

export function parseSessionToken(token: string | undefined): SessionPayload | null {
  if (!token) return null;
  const [encoded, signature] = token.split(".");
  if (!encoded || !signature) return null;
  const expectedSignature = signValue(encoded);
  if (signature.length !== expectedSignature.length) return null;
  const isValid = timingSafeEqual(Buffer.from(signature), Buffer.from(expectedSignature));
  if (!isValid) return null;

  try {
    const payload = JSON.parse(fromBase64Url(encoded)) as SessionPayload;
    if (!payload.exp || payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}
