import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "./client";

describe("apiFetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("throws ApiError with response body on non-2xx", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(new Response("boom", { status: 500, headers: { "Content-Type": "text/plain" } }));
    fetchSpy.mockResolvedValueOnce(new Response("boom", { status: 500, headers: { "Content-Type": "text/plain" } }));

    await expect(apiFetch("/api/v1/reviews")).rejects.toBeInstanceOf(ApiError);
    await expect(apiFetch("/api/v1/reviews")).rejects.toMatchObject({ status: 500 });
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
