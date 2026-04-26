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
});
