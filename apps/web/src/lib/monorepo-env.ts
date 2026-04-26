import fs from "node:fs";
import path from "node:path";

/** True after we have walked ancestor dirs looking for OAuth vars (success or not). */
let githubOAuthScanDone = false;

function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

function parseDotEnvContent(content: string): Record<string, string> {
  const out: Record<string, string> = {};
  const text = stripBom(content);
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const withoutExport = trimmed.startsWith("export ") ? trimmed.slice(7).trim() : trimmed;
    const eq = withoutExport.indexOf("=");
    if (eq <= 0) continue;
    const key = withoutExport.slice(0, eq).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;
    let val = withoutExport.slice(eq + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'")))
      val = val.slice(1, -1);
    out[key] = val;
  }
  return out;
}

function applyGithubOAuthFromFile(filePath: string): void {
  const parsed = parseDotEnvContent(fs.readFileSync(filePath, "utf8"));
  if (!process.env.GITHUB_CLIENT_ID?.trim() && parsed.GITHUB_CLIENT_ID?.trim()) {
    process.env.GITHUB_CLIENT_ID = parsed.GITHUB_CLIENT_ID.trim();
  }
  if (!process.env.GITHUB_CLIENT_SECRET?.trim() && parsed.GITHUB_CLIENT_SECRET?.trim()) {
    process.env.GITHUB_CLIENT_SECRET = parsed.GITHUB_CLIENT_SECRET.trim();
  }
}

/**
 * Next.js only auto-loads `.env*` from `apps/web`. Repo-root `.env.local` is ignored unless
 * `next.config` picked it up (which can fail if `__dirname` is wrong when the config is bundled).
 * Walk up from `process.cwd()` and merge `GITHUB_CLIENT_*` from the first readable `.env.local` / `.env`
 * in each directory until both are set or the filesystem root is reached.
 */
export function hydrateGithubOAuthEnvFromAncestors(): void {
  if (process.env.GITHUB_CLIENT_ID?.trim() && process.env.GITHUB_CLIENT_SECRET?.trim()) return;
  if (githubOAuthScanDone) return;
  githubOAuthScanDone = true;

  let dir = path.resolve(process.cwd());
  for (let i = 0; i < 16; i++) {
    for (const name of [".env.local", ".env"] as const) {
      const full = path.join(dir, name);
      if (!fs.existsSync(full)) continue;
      try {
        applyGithubOAuthFromFile(full);
      } catch {
        /* unreadable or race; skip */
      }
    }
    if (process.env.GITHUB_CLIENT_ID?.trim() && process.env.GITHUB_CLIENT_SECRET?.trim()) return;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
}
