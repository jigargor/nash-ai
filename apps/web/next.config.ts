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
loadEnvConfig(
  findMonorepoRoot(__dirname),
  process.env.NODE_ENV !== "production",
);

// default-src alone blocks inline script/style that React/Next hydration relies on.
// React + Next dev tooling (e.g. Turbopack, stack reconstruction) uses eval(); never in production bundles.
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";

const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
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
