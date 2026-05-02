"use client";

import { useMemo, useState } from "react";

import { TurnstileWidget } from "@/components/security/turnstile-widget";

export function LoginTurnstileForm() {
  const turnstileSiteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [turnstileError, setTurnstileError] = useState<string | null>(null);

  const requiresTurnstile = useMemo(
    () => Boolean(turnstileSiteKey && turnstileSiteKey.trim().length > 0),
    [turnstileSiteKey],
  );
  const isSubmitDisabled = requiresTurnstile && !turnstileToken;

  return (
    <form action="/api/v1/auth/login" method="post" className="login-form">
      {requiresTurnstile ? (
        <div style={{ display: "grid", gap: "0.45rem", marginTop: "0.45rem" }}>
          <TurnstileWidget
            siteKey={turnstileSiteKey as string}
            onToken={(token) => {
              setTurnstileError(null);
              setTurnstileToken(token);
            }}
            onError={() => setTurnstileError("Security check failed to load. Refresh and try again.")}
          />
          {turnstileError ? (
            <p className="login-error" style={{ margin: 0 }} role="alert">
              {turnstileError}
            </p>
          ) : null}
        </div>
      ) : null}
      <input type="hidden" name="turnstile_token" value={turnstileToken ?? ""} />
      <button type="submit" className="button button-primary login-submit" disabled={isSubmitDisabled}>
        Continue with GitHub
      </button>
    </form>
  );
}
