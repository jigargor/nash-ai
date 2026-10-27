/**
 * Resolve the same-origin base URL used by server-side loopback calls to the Next.js BFF.
 *
 * Only the `Host` header is considered (never `X-Forwarded-Host` / `X-Forwarded-Proto`, which a
 * client can spoof to turn the loopback call into SSRF with the caller's session cookie attached).
 */

const HOST_PATTERN = /^[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?$/i;
const LOCAL_HOSTNAMES = new Set(["localhost", "127.0.0.1"]);
const DEFAULT_LOCAL_HOST = "localhost:3000";

export interface BffBaseUrlEnv {
  NODE_ENV?: string;
  VERCEL?: string;
  WEB_APP_URL?: string;
  NEXT_PUBLIC_WEB_APP_URL?: string;
  VERCEL_URL?: string;
  VERCEL_PROJECT_PRODUCTION_URL?: string;
}

function hostnameOf(host: string): string {
  return host.split(":")[0]?.toLowerCase() ?? "";
}

function hostFromUrlLike(value: string | undefined): string | null {
  if (!value?.trim()) return null;
  const trimmed = value.trim();
  try {
    return new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`).host.toLowerCase();
  } catch {
    return null;
  }
}

function allowedProductionHosts(env: BffBaseUrlEnv): Set<string> {
  const hosts = [
    env.WEB_APP_URL,
    env.NEXT_PUBLIC_WEB_APP_URL,
    env.VERCEL_URL,
    env.VERCEL_PROJECT_PRODUCTION_URL,
  ]
    .map(hostFromUrlLike)
    .filter((host): host is string => host !== null);
  return new Set(hosts);
}

export function isSafeHostHeader(host: string | null | undefined): host is string {
  return typeof host === "string" && host.length > 0 && host.length <= 255 && HOST_PATTERN.test(host);
}

/** Returns `proto://host` for the loopback call, or throws when the Host header is not trusted. */
export function resolveBffBaseUrl(hostHeader: string | null | undefined, env: BffBaseUrlEnv): string {
  const isProduction = env.NODE_ENV === "production" || env.VERCEL === "1";
  const host = hostHeader ?? DEFAULT_LOCAL_HOST;
  if (!isSafeHostHeader(host)) throw new Error("serverBffFetch: rejected untrusted Host header.");

  const normalizedHost = host.toLowerCase();
  const isLocal = LOCAL_HOSTNAMES.has(hostnameOf(normalizedHost));
  if (isLocal) return `http://${normalizedHost}`;

  if (isProduction && !allowedProductionHosts(env).has(normalizedHost))
    throw new Error("serverBffFetch: Host header does not match the configured web app origin.");

  return `${isProduction ? "https" : "http"}://${normalizedHost}`;
}
