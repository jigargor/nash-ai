import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DASHBOARD_ROUTE_PREFIXES, isDashboardRoute } from "@/lib/auth/dashboard-routes";

const parseSessionTokenMock = vi.fn();

vi.mock("@/lib/auth/session", () => ({
  parseSessionToken: (token: string | undefined) => parseSessionTokenMock(token),
}));

import { config, proxy } from "@/proxy";

describe("dashboard route protection", () => {
  beforeEach(() => {
    parseSessionTokenMock.mockReset();
    parseSessionTokenMock.mockResolvedValue(null);
  });

  it("treats /models and /evaluate-external as dashboard routes", () => {
    expect(isDashboardRoute("/models")).toBe(true);
    expect(isDashboardRoute("/evaluate-external")).toBe(true);
    expect(isDashboardRoute("/evaluate-external/123")).toBe(true);
    expect(isDashboardRoute("/modelsfoo")).toBe(false);
    expect(isDashboardRoute("/about")).toBe(false);
  });

  it("includes every protected prefix in the proxy matcher", () => {
    for (const prefix of DASHBOARD_ROUTE_PREFIXES) {
      expect(config.matcher).toContain(`${prefix}/:path*`);
    }
  });

  it.each(["/models", "/evaluate-external"])("redirects unauthenticated %s to login", async (path) => {
    const response = await proxy(new NextRequest(`http://localhost:3000${path}`));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe(path);
  });

  it("allows authenticated access to /models", async () => {
    parseSessionTokenMock.mockResolvedValue({ sub: "1" });
    const response = await proxy(new NextRequest("http://localhost:3000/models"));
    expect(response.headers.get("location")).toBeNull();
  });
});
