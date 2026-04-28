import fs from "node:fs";
import path from "node:path";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

function findMonorepoRoot(startDir: string): string {
  let dir = path.resolve(startDir);
  for (let i = 0; i < 16; i++) {
    if (fs.existsSync(path.join(dir, "pnpm-workspace.yaml"))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.resolve(startDir, "..", "..");
}

// Repo-root `.env.local` (OAuth, etc.): Next only auto-loads `apps/web` by default; `__dirname` can
// also be wrong when this file is bundled, so resolve root via `pnpm-workspace.yaml` when possible.
const monorepoRoot = findMonorepoRoot(__dirname);
loadEnvConfig(
  monorepoRoot,
  process.env.NODE_ENV !== "production",
);

/**
 * CSP `form-action` applies to form submission navigations, **including redirect targets**. The
 * login POST redirects to `https://github.com/login/oauth/authorize`, so `'self'` alone blocks the
 * OAuth handoff. We always allow GitHub plus optional origins from WEB_APP_URL (www/apex, etc.).
 */
function expandWwwApexOrigins(canonicalInput: string): string[] {
  let url: URL;
  try {
    url = new URL(canonicalInput);
  } catch {
    return [];
  }
  const host = url.hostname;
  const port = url.port ? `:${url.port}` : "";
  const base = (h: string) => `${url.protocol}//${h}${port}`;
  const out = new Set<string>([base(host)]);
  if (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    /^\d+\.\d+\.\d+\.\d+$/.test(host) ||
    host.endsWith(".vercel.app")
  ) {
    return [...out];
  }
  if (host.startsWith("www.")) {
    out.add(base(host.slice(4)));
  } else {
    out.add(base(`www.${host}`));
  }
  return [...out];
}

function extractOriginTokens(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((token) => token.trim())
    .filter(Boolean);
}

function sanitizeOriginToken(token: string): string | null {
  // Drop unresolved placeholders (for example "$VERCEL_URL") from hosting dashboards.
  if (token.includes("$")) return null;
  let url: URL;
  try {
    url = new URL(token);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  return `${url.protocol}//${url.host}`;
}

function buildFormActionDirective(): string {
  const origins = new Set<string>(["https://github.com"]);

  const tokens = [
    process.env.WEB_APP_URL,
    process.env.NEXT_PUBLIC_WEB_APP_URL,
    process.env.CSP_FORM_ACTION_EXTRA,
    process.env.VERCEL === "1" && process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "",
  ]
    .filter(Boolean)
    .flatMap((value) => extractOriginTokens(String(value)));

  for (const token of tokens) {
    const sanitizedOrigin = sanitizeOriginToken(token);
    if (!sanitizedOrigin) continue;
    for (const o of expandWwwApexOrigins(sanitizedOrigin)) {
      if (o) origins.add(o);
    }
  }

  return `form-action 'self' ${[...origins].sort().join(" ")}`;
}

// default-src alone blocks inline script/style that React/Next hydration relies on.
// React + Next dev tooling (e.g. Turbopack, stack reconstruction) uses eval(); never in production bundles.
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";

const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  buildFormActionDirective(),
  "frame-ancestors 'none'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  // Allow HTTPS APIs when NEXT_PUBLIC_* points at Railway (or OAuth); prefer same-origin /api/* via BFF.
  "connect-src 'self' https:",
  scriptSrc,
  "style-src 'self' 'unsafe-inline'",
].join("; ");

const securityHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=15552000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Content-Security-Policy", value: csp },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  turbopack: {
    root: monorepoRoot,
  },
  images: {
    // Next.js 16+: local src with query strings must match localPatterns (omit `search` to allow any ?v=…).
    localPatterns: [{ pathname: "/logo.png" }, { pathname: "/me.png" }],
    // In dev, avoid long-lived /_next/image optimizer cache when iterating on public/logo.png.
    ...(isDev ? { minimumCacheTTL: 0 } : {}),
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
      {
        source: "/logo.png",
        headers: [{ key: "Cache-Control", value: "public, max-age=0, must-revalidate" }],
      },
    ];
  },
};

export default nextConfig;
