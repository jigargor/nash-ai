import { afterEach, describe, expect, it, vi } from "vitest";

import { AUTH_PKCE_VERIFIER_COOKIE_NAME, AUTH_STATE_COOKIE_NAME } from "@/lib/auth/constants";

const cookiesMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: cookiesMock,
}));

describe("auth callback route", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("redirects with pkce_mismatch when verifier cookie is missing", async () => {
    cookiesMock.mockResolvedValue({
      get: vi.fn((name: string) => {
        if (name === AUTH_STATE_COOKIE_NAME) return { value: "state-123" };
        if (name === AUTH_PKCE_VERIFIER_COOKIE_NAME) return undefined;
        return undefined;
      }),
    });

    const routeModule = await import("./route");
    const response = await routeModule.GET(
      new Request("http://localhost:3000/api/v1/auth/callback?code=oauth-code&state=state-123"),
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain("/login?error=pkce_mismatch");
  });
});
