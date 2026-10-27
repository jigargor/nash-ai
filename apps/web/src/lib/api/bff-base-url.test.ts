import { describe, expect, it } from "vitest";

import { resolveBffBaseUrl } from "@/lib/api/bff-base-url";

describe("resolveBffBaseUrl", () => {
  it("uses http for localhost in development", () => {
    expect(resolveBffBaseUrl("localhost:3000", { NODE_ENV: "development" })).toBe("http://localhost:3000");
    expect(resolveBffBaseUrl(null, { NODE_ENV: "development" })).toBe("http://localhost:3000");
  });

  it("keeps localhost on http in production (e.g. `next start`)", () => {
    expect(resolveBffBaseUrl("127.0.0.1:3000", { NODE_ENV: "production" })).toBe("http://127.0.0.1:3000");
  });

  it("rejects hosts with unexpected characters", () => {
    for (const bad of ["evil.com/path", "a@evil.com", "evil.com\r\nX: 1", "evil.com#", "", "a b.com"])
      expect(() => resolveBffBaseUrl(bad, { NODE_ENV: "development" })).toThrow();
  });

  it("rejects non-allowlisted hosts in production", () => {
    expect(() => resolveBffBaseUrl("evil.example", { NODE_ENV: "production", WEB_APP_URL: "https://app.example.com" })).toThrow();
    expect(() => resolveBffBaseUrl("evil.example", { NODE_ENV: "production" })).toThrow();
  });

  it("allows host matching WEB_APP_URL in production over https", () => {
    expect(
      resolveBffBaseUrl("App.Example.com", { NODE_ENV: "production", WEB_APP_URL: "https://app.example.com" }),
    ).toBe("https://app.example.com");
    expect(
      resolveBffBaseUrl("x.vercel.app", { VERCEL: "1", VERCEL_URL: "x.vercel.app" }),
    ).toBe("https://x.vercel.app");
  });
});
