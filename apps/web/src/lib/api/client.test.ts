import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, assertBrowserDashboardApiPath, apiFetch } from "./client";

describe("apiFetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("throws ApiError with response body on non-2xx", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: "DEPENDENCY_REDIS_UNAVAILABLE",
            family: "dependency",
            message: "Redis unavailable",
            retryable: true,
            action: "retry",
            request_id: "req-123",
          },
          detail: "Redis unavailable",
        }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(apiFetch("/api/v1/reviews")).rejects.toMatchObject({
      status: 503,
      code: "DEPENDENCY_REDIS_UNAVAILABLE",
      family: "dependency",
      retryable: true,
      action: "retry",
      requestId: "req-123",
      message: "Redis unavailable",
    });
  });

  it("throws ApiError when payload is empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("null", { status: 200 }));

    await expect(apiFetch("/api/v1/reviews")).rejects.toBeInstanceOf(ApiError);
  });

  it("does not send /api/* to NEXT_PUBLIC_API_BASE (same-origin BFF + CSP)", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_API_BASE", "https://nash-ai-api-production.up.railway.app");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    const { apiFetch: apiFetchFresh } = await import("./client");
    await apiFetchFresh("/api/v1/reviews");
    expect(fetchSpy.mock.calls[0]?.[0]).toBe("/api/v1/reviews");
  });
});

describe("assertBrowserDashboardApiPath", () => {
  it("rejects non-BFF URLs and paths when running in a browser", () => {
    const original = globalThis.window;
    vi.stubGlobal("window", {} as Window & typeof globalThis);
    try {
      expect(() => assertBrowserDashboardApiPath("/v1/foo")).toThrow(/BFF/);
      expect(() => assertBrowserDashboardApiPath("https://api.example/upstream")).toThrow(/BFF/);
    } finally {
      vi.stubGlobal("window", original);
    }
  });
});
