import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";

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
      get: vi.fn((name: string) => {
        if (name === AUTH_COOKIE_NAME) return { value: "session-cookie-token" };
        return undefined;
      }),
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
    const body = await response.json();
    expect(body.detail).toBe("Unauthorized");
    expect(body.error).toMatchObject({
      code: "AUTH_UNAUTHORIZED",
      action: "reauth",
    });
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

  it("rejects rerun requests when cf_clearance cookie is missing", async () => {
    parseSessionTokenMock.mockResolvedValue({
      sub: "12345",
      user: { id: 12345, login: "octocat" },
      exp: Math.floor(Date.now() / 1000) + 60,
    });
    createDashboardUserTokenMock.mockReturnValue("server-minted-dashboard-token");
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const routeModule = await import("./route");
    const request = new Request("http://localhost:3000/api/v1/reviews/123/rerun?installation_id=1", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    const response = await routeModule.POST(request, {
      params: Promise.resolve({ path: ["reviews", "123", "rerun"] }),
    });

    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      detail: "Turnstile clearance cookie required to re-run reviews.",
      error: {
        code: "AUTH_CLEARANCE_REQUIRED",
        family: "auth",
        action: "none",
        message: "Turnstile clearance cookie required to re-run reviews.",
        retryable: false,
      },
    });
    expect(fetchSpy).not.toHaveBeenCalled();
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
    const body = await response.json();
    expect(body.detail).toBe("Request body exceeds 1048576 byte limit.");
    expect(body.error).toMatchObject({
      code: "VALIDATION_BODY_TOO_LARGE",
      action: "fix_input",
    });
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

  it("normalizes legacy upstream errors into the canonical envelope", async () => {
    parseSessionTokenMock.mockResolvedValue({
      sub: "12345",
      user: { id: 12345, login: "octocat" },
      exp: Math.floor(Date.now() / 1000) + 60,
    });
    createDashboardUserTokenMock.mockReturnValue("server-minted-dashboard-token");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Redis unavailable" }), {
        status: 503,
        headers: { "content-type": "application/json", "X-Request-ID": "api-req-1" },
      }),
    );

    const routeModule = await import("./route");
    const request = new Request("http://localhost:3000/api/v1/reviews", { method: "GET" });
    const response = await routeModule.GET(request, {
      params: Promise.resolve({ path: ["reviews"] }),
    });

    expect(response.status).toBe(503);
    expect(response.headers.get("X-Request-ID")).toBe("api-req-1");
    const body = await response.json();
    expect(body.detail).toBe("Redis unavailable");
    expect(body.error).toMatchObject({
      code: "DEPENDENCY_UNAVAILABLE",
      family: "dependency",
      action: "retry",
      request_id: "api-req-1",
    });
  });

  it("forwards cf_clearance to backend when present", async () => {
    parseSessionTokenMock.mockResolvedValue({
      sub: "12345",
      user: { id: 12345, login: "octocat" },
      exp: Math.floor(Date.now() / 1000) + 60,
    });
    createDashboardUserTokenMock.mockReturnValue("server-minted-dashboard-token");
    cookiesMock.mockResolvedValue({
      get: vi.fn((name: string) => {
        if (name === AUTH_COOKIE_NAME) return { value: "session-cookie-token" };
        if (name === "cf_clearance") return { value: "cf-clearance-token" };
        return undefined;
      }),
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const routeModule = await import("./route");
    const request = new Request("http://localhost:3000/api/v1/reviews/123/rerun?installation_id=1", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    await routeModule.POST(request, {
      params: Promise.resolve({ path: ["reviews", "123", "rerun"] }),
    });

    const fetchCall = fetchSpy.mock.calls[0];
    const options = fetchCall?.[1] as RequestInit | undefined;
    const forwardedHeaders = options?.headers as Headers;
    expect(forwardedHeaders.get("X-CF-Clearance")).toBe("cf-clearance-token");
  });
});
