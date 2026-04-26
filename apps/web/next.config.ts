import type { NextConfig } from "next";

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
