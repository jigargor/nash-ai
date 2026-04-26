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
const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
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
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
