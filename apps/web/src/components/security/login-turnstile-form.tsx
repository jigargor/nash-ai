"use client";

import { useCallback, useEffect, useState } from "react";

import { TurnstileWidget } from "@/components/security/turnstile-widget";

const TURNSTILE_SLOW_LOAD_MS = 12_000;

function turnstileErrorMessage(errorCode?: string | number): string {
  if (!errorCode) {
    return "Security check failed to load. Refresh and try again.";
  }

  return `Security check failed (${errorCode}). Retry, or disable browser extensions that block Cloudflare challenges.`;
}

export function LoginTurnstileForm() {
  const turnstileSiteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY?.trim() ?? "";
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [turnstileError, setTurnstileError] = useState<string | null>(null);
  const [turnstileResetKey, setTurnstileResetKey] = useState(0);

  const requiresTurnstile = turnstileSiteKey.length > 0;
  const isSubmitDisabled = requiresTurnstile && !turnstileToken;
  const handleRetryTurnstile = useCallback(() => {
    setTurnstileError(null);
    setTurnstileToken(null);
    setTurnstileResetKey((current) => current + 1);
  }, []);
  const handleTurnstileToken = useCallback((token: string) => {
    setTurnstileError(null);
    setTurnstileToken(token);
  }, []);
  const handleTurnstileError = useCallback((errorCode?: string | number) => {
    setTurnstileToken(null);
    setTurnstileError(turnstileErrorMessage(errorCode));
  }, []);
  const handleTurnstileExpired = useCallback(() => {
    setTurnstileToken(null);
    setTurnstileError("Security check expired. Please complete it again.");
  }, []);
  const handleTurnstileTimeout = useCallback(() => {
    setTurnstileToken(null);
    setTurnstileError("Security check timed out. Retry the challenge to continue.");
  }, []);
  const handleTurnstileUnsupported = useCallback(() => {
    setTurnstileToken(null);
    setTurnstileError("This browser is not supported by the security check. Try a current browser without blockers.");
  }, []);

  useEffect(() => {
    if (!requiresTurnstile || turnstileToken) return;

    const timeoutId = window.setTimeout(() => {
      setTurnstileError(
        "Security check is taking longer than expected. Retry, or disable browser extensions that block Cloudflare challenges.",
      );
    }, TURNSTILE_SLOW_LOAD_MS);

    return () => window.clearTimeout(timeoutId);
  }, [requiresTurnstile, turnstileResetKey, turnstileToken]);

  return (
    <form action="/api/v1/auth/login" method="post" className="login-form">
      {requiresTurnstile ? (
        <div style={{ display: "grid", gap: "0.45rem", marginTop: "0.45rem" }}>
          <TurnstileWidget
            key={turnstileResetKey}
            siteKey={turnstileSiteKey}
            onError={handleTurnstileError}
            onExpired={handleTurnstileExpired}
            onTimeout={handleTurnstileTimeout}
            onToken={handleTurnstileToken}
            onUnsupported={handleTurnstileUnsupported}
          />
          {turnstileError ? (
            <>
              <p className="login-error" style={{ margin: 0 }} role="alert">
                {turnstileError}
              </p>
              <button type="button" className="button button-ghost" onClick={handleRetryTurnstile}>
                Retry security check
              </button>
            </>
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
