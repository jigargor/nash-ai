export interface GitHubOAuthTokenResponse {
  access_token: string;
  token_type: string;
  scope: string;
}

export interface GitHubUser {
  id: number;
  login: string;
}

export interface GitHubUserInstallation {
  id: number;
  account: {
    login: string;
    type: string;
  };
}

function getGitHubClientId(): string {
  const value = process.env.GITHUB_CLIENT_ID;
  if (!value) throw new Error("Missing GITHUB_CLIENT_ID");
  return value;
}

function getGitHubClientSecret(): string {
  const value = process.env.GITHUB_CLIENT_SECRET;
  if (!value) throw new Error("Missing GITHUB_CLIENT_SECRET");
  return value;
}

export function buildGitHubAuthorizeUrl(
  state: string,
  redirectUri: string,
  codeChallenge: string,
): string {
  const params = new URLSearchParams({
    client_id: getGitHubClientId(),
    redirect_uri: redirectUri,
    scope: "read:user read:org",
    state,
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
  });
  return `https://github.com/login/oauth/authorize?${params.toString()}`;
}

export async function exchangeCodeForToken(
  code: string,
  redirectUri: string,
  codeVerifier: string,
): Promise<GitHubOAuthTokenResponse> {
  const response = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      client_id: getGitHubClientId(),
      client_secret: getGitHubClientSecret(),
      code,
      redirect_uri: redirectUri,
      code_verifier: codeVerifier,
    }),
    cache: "no-store",
  });
  if (!response.ok) throw new Error("GitHub token exchange failed");
  return (await response.json()) as GitHubOAuthTokenResponse;
}

export async function getGitHubUser(accessToken: string): Promise<GitHubUser> {
  const response = await fetch("https://api.github.com/user", {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    cache: "no-store",
  });
  if (!response.ok) throw new Error("Failed to fetch GitHub user profile");
  return (await response.json()) as GitHubUser;
}

export async function listGitHubUserInstallations(
  accessToken: string,
): Promise<GitHubUserInstallation[]> {
  const response = await fetch("https://api.github.com/user/installations?per_page=100", {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    cache: "no-store",
  });
  if (!response.ok) throw new Error("Failed to fetch GitHub user installations");
  const payload = (await response.json()) as {
    installations?: GitHubUserInstallation[];
  };
  return Array.isArray(payload.installations) ? payload.installations : [];
}
