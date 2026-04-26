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
  const secret = process.env.AUTH_SESSION_SECRET?.trim();
  if (secret) return secret;
  if (process.env.NODE_ENV === "production") {
    throw new Error("Missing AUTH_SESSION_SECRET in production");
  }
  return "dev-insecure-session-secret";
}

let hmacKeyPromise: Promise<CryptoKey> | null = null;
let hmacKeySecret = "";

async function getHmacKey(): Promise<CryptoKey> {
  const secret = getSessionSecret();
  if (!hmacKeyPromise || hmacKeySecret !== secret) {
    hmacKeySecret = secret;
    const encoder = new TextEncoder();
    hmacKeyPromise = crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
  }
  return hmacKeyPromise;
}

function uint8ArrayToBase64Url(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]!);
  const b64 = btoa(bin);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlToUint8Array(b64: string): Uint8Array {
  const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
  const b64norm = b64.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const bin = atob(b64norm);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)!;
  return out;
}

function utf8ToBase64Url(str: string): string {
  return uint8ArrayToBase64Url(new TextEncoder().encode(str));
}

function base64UrlToUtf8(b64: string): string {
  return new TextDecoder().decode(base64UrlToUint8Array(b64));
}

function timingSafeEqualBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}

async function signValue(value: string): Promise<string> {
  const key = await getHmacKey();
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return uint8ArrayToBase64Url(new Uint8Array(sig));
}

export function createOAuthState(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return uint8ArrayToBase64Url(bytes);
}

export async function createSessionToken(user: SessionUser): Promise<string> {
  const payload: SessionPayload = {
    sub: String(user.id),
    user,
    exp: Math.floor(Date.now() / 1000) + AUTH_COOKIE_TTL_SECONDS,
  };
  const encoded = utf8ToBase64Url(JSON.stringify(payload));
  const signature = await signValue(encoded);
  return `${encoded}.${signature}`;
}

export async function parseSessionToken(token: string | undefined): Promise<SessionPayload | null> {
  if (!token) return null;
  const [encoded, signature] = token.split(".");
  if (!encoded || !signature) return null;
  const expectedSignature = await signValue(encoded);
  const sigBytes = base64UrlToUint8Array(signature);
  const expectedSigBytes = base64UrlToUint8Array(expectedSignature);
  if (!timingSafeEqualBytes(sigBytes, expectedSigBytes)) return null;

  try {
    const payload = JSON.parse(base64UrlToUtf8(encoded)) as SessionPayload;
    if (!payload.exp || payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}
