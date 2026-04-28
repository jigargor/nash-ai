import { afterEach, describe, expect, it, vi } from "vitest";

import { buildGitHubAuthorizeUrl, exchangeCodeForToken } from "./github";

describe("github oauth helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it("builds authorize URL with PKCE challenge parameters", () => {
    vi.stubEnv("GITHUB_CLIENT_ID", "client-id-123");

    const url = buildGitHubAuthorizeUrl("state-token", "https://app.example.com/api/v1/auth/callback", "pkce-hash");
    const parsed = new URL(url);

    expect(parsed.origin).toBe("https://github.com");
    expect(parsed.pathname).toBe("/login/oauth/authorize");
    expect(parsed.searchParams.get("client_id")).toBe("client-id-123");
    expect(parsed.searchParams.get("state")).toBe("state-token");
    expect(parsed.searchParams.get("code_challenge")).toBe("pkce-hash");
    expect(parsed.searchParams.get("code_challenge_method")).toBe("S256");
  });

  it("sends PKCE verifier in token exchange request body", async () => {
    vi.stubEnv("GITHUB_CLIENT_ID", "client-id-123");
    vi.stubEnv("GITHUB_CLIENT_SECRET", "client-secret-xyz");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ access_token: "token", token_type: "bearer", scope: "read:user" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await exchangeCodeForToken("oauth-code", "https://app.example.com/api/v1/auth/callback", "pkce-verifier");

    const body = JSON.parse(String((fetchSpy.mock.calls[0]?.[1] as RequestInit).body));
    expect(body.code_verifier).toBe("pkce-verifier");
    expect(body.code).toBe("oauth-code");
  });
});
