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

const nextConfig: NextConfig = {
  async rewrites() {
    const apiBase = process.env.API_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/v1/reviews/:path*",
        destination: `${apiBase}/api/v1/reviews/:path*`,
      },
      {
        source: "/api/v1/installations/:path*",
        destination: `${apiBase}/api/v1/installations/:path*`,
      },
      {
        source: "/api/v1/telemetry/:path*",
        destination: `${apiBase}/api/v1/telemetry/:path*`,
      },
    ];
  },
};

export default nextConfig;
