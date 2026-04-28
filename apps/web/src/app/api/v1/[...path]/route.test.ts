import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const cookiesMock = vi.fn();
const parseSessionTokenMock = vi.fn();
const createDashboardUserTokenMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: cookiesMock,
}));

vi.mock("@/lib/auth/session", () => ({
  parseSessionToken: parseSessionTokenMock,
}));

vi.mock("@/lib/auth/dashboard-token", () => ({
  createDashboardUserToken: createDashboardUserTokenMock,
}));

describe("api v1 proxy route", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubEnv("API_ACCESS_KEY", "service-secret");
    vi.stubEnv("API_URL", "http://api.example.local");
    cookiesMock.mockResolvedValue({
      get: vi.fn().mockReturnValue({ value: "session-cookie-token" }),
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("returns 401 when session is missing", async () => {
    parseSessionTokenMock.mockResolvedValue(null);

    const routeModule = await import("./route");
    const request = new Request("http://localhost:3000/api/v1/users/me/keys", { method: "GET" });
    const response = await routeModule.GET(request, {
      params: Promise.resolve({ path: ["users", "me", "keys"] }),
    });

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ detail: "Unauthorized" });
  });

  it("forwards api key and server-minted user token", async () => {
    parseSessionTokenMock.mockResolvedValue({
      sub: "12345",
      user: { id: 12345, login: "octocat" },
      exp: Math.floor(Date.now() / 1000) + 60,
    });
    createDashboardUserTokenMock.mockReturnValue("server-minted-dashboard-token");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const routeModule = await import("./route");
    const request = new Request("http://localhost:3000/api/v1/users/me/keys?validate=false", {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        "X-User-Github-Id": "999999",
        "X-Dashboard-User-Token": "spoofed-token",
      },
      body: JSON.stringify({ api_key: "sk-test-key" }),
    });
    await routeModule.PUT(request, {
      params: Promise.resolve({ path: ["users", "me", "keys", "openai"] }),
    });

    const fetchCall = fetchSpy.mock.calls[0];
    expect(fetchCall).toBeDefined();
    expect(String(fetchCall?.[0])).toContain("/api/v1/users/me/keys/openai?validate=false");
    const options = fetchCall?.[1] as RequestInit | undefined;
    const forwardedHeaders = options?.headers as Headers;
    expect(forwardedHeaders.get("X-Api-Key")).toBe("service-secret");
    expect(forwardedHeaders.get("X-Dashboard-User-Token")).toBe("server-minted-dashboard-token");
    expect(forwardedHeaders.get("X-User-Github-Id")).toBeNull();
  });

  it("rejects oversized request bodies with 413", async () => {
    parseSessionTokenMock.mockResolvedValue({
      sub: "12345",
      user: { id: 12345, login: "octocat" },
      exp: Math.floor(Date.now() / 1000) + 60,
    });
    createDashboardUserTokenMock.mockReturnValue("server-minted-dashboard-token");
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const routeModule = await import("./route");
    const request = new Request("http://localhost:3000/api/v1/users/me/keys", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "content-length": String(1024 * 1024 + 1),
      },
      body: JSON.stringify({ payload: "small-body-but-header-is-large" }),
    });

    const response = await routeModule.POST(request, {
      params: Promise.resolve({ path: ["users", "me", "keys"] }),
    });

    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({ detail: "Request body exceeds 1048576 byte limit." });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("supports patch requests through the same proxy path", async () => {
    parseSessionTokenMock.mockResolvedValue({
      sub: "12345",
      user: { id: 12345, login: "octocat" },
      exp: Math.floor(Date.now() / 1000) + 60,
    });
    createDashboardUserTokenMock.mockReturnValue("server-minted-dashboard-token");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const routeModule = await import("./route");
    const request = new Request("http://localhost:3000/api/v1/reviews/1", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status: "queued" }),
    });

    const response = await routeModule.PATCH(request, {
      params: Promise.resolve({ path: ["reviews", "1"] }),
    });

    expect(response.status).toBe(200);
    const fetchCall = fetchSpy.mock.calls[0];
    const options = fetchCall?.[1] as RequestInit | undefined;
    expect(options?.method).toBe("PATCH");
  });
});
