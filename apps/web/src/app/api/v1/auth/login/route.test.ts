import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AUTH_PKCE_VERIFIER_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
} from "@/lib/auth/constants";

const cookiesMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: cookiesMock,
}));

async function loadRouteModule() {
  vi.resetModules();
  return import("./route");
}

describe("auth login route", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    cookiesMock.mockReset();
  });

  it("returns 303 to GitHub and sets oauth cookies on successful POST", async () => {
    vi.stubEnv("GITHUB_CLIENT_ID", "test-client-id");
    vi.stubEnv("GITHUB_CLIENT_SECRET", "test-client-secret");

    const requestBody = new URLSearchParams();
    const request = new Request("https://nash-ai.app/api/v1/auth/login", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: requestBody.toString(),
    });

    const routeModule = await loadRouteModule();
    const response = await routeModule.POST(request);

    expect(response.status).toBe(303);
    const location = response.headers.get("location");
    expect(location).toBeTruthy();
    expect(location?.startsWith("https://github.com/login/oauth/authorize?")).toBe(true);

    const authorizeUrl = new URL(location as string);
    expect(authorizeUrl.searchParams.get("client_id")).toBe("test-client-id");
    expect(authorizeUrl.searchParams.get("redirect_uri")).toBe("https://nash-ai.app/api/v1/auth/callback");
    expect(authorizeUrl.searchParams.get("scope")).toBe("read:user read:org");
    expect(authorizeUrl.searchParams.get("code_challenge_method")).toBe("S256");

    expect(response.cookies.get(AUTH_STATE_COOKIE_NAME)?.value).toBeTruthy();
    expect(response.cookies.get(AUTH_PKCE_VERIFIER_COOKIE_NAME)?.value).toBeTruthy();
  });

  it("returns 503 JSON when OAuth env is not configured", async () => {
    vi.stubEnv("GITHUB_CLIENT_ID", "");
    vi.stubEnv("GITHUB_CLIENT_SECRET", "");

    const request = new Request("https://nash-ai.app/api/v1/auth/login", {
      method: "POST",
      body: new URLSearchParams().toString(),
      headers: { "content-type": "application/x-www-form-urlencoded" },
    });

    const routeModule = await loadRouteModule();
    const response = await routeModule.POST(request);
    const body = (await response.json()) as { error?: string };

    expect(response.status).toBe(503);
    expect(body.error).toContain("GitHub OAuth is not configured");
  });

  it("GET redirects directly to GitHub authorize URL", async () => {
    vi.stubEnv("GITHUB_CLIENT_ID", "test-client-id");
    vi.stubEnv("GITHUB_CLIENT_SECRET", "test-client-secret");
    cookiesMock.mockResolvedValue({
      get: vi.fn(() => undefined),
    });

    const routeModule = await loadRouteModule();
    const response = await routeModule.GET(new Request("https://nash-ai.app/api/v1/auth/login"));

    expect(response.status).toBe(307);
    expect(response.headers.get("location")?.startsWith("https://github.com/login/oauth/authorize?")).toBe(true);
  });
});
