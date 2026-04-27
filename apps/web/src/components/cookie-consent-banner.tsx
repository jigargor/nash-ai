"use client";

import Link from "next/link";
import { useState } from "react";

import {
  buildCookieConsentCookieValue,
  COOKIE_CONSENT_COOKIE_NAME,
  COOKIE_CONSENT_MAX_AGE_SECONDS,
} from "@/lib/cookie-consent";

function readConsentFromDocument(): boolean {
  const needle = `${COOKIE_CONSENT_COOKIE_NAME}=`;
  return document.cookie.split(";").some((part) => part.trim().startsWith(needle));
}

function writeConsentCookie(): void {
  const secure = globalThis.location.protocol === "https:";
  const value = buildCookieConsentCookieValue();
  document.cookie = `${COOKIE_CONSENT_COOKIE_NAME}=${encodeURIComponent(value)}; Path=/; Max-Age=${String(COOKIE_CONSENT_MAX_AGE_SECONDS)}; SameSite=Lax${secure ? "; Secure" : ""}`;
}

export function CookieConsentBanner() {
  const [show, setShow] = useState(() => !readConsentFromDocument());

  function handleAccept() {
    writeConsentCookie();
    setShow(false);
  }

  if (!show) return null;

  return (
    <div
      className="cookie-consent-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cookie-consent-title"
      aria-describedby="cookie-consent-desc"
    >
      <div className="cookie-consent-modal">
        <h2 id="cookie-consent-title" className="cookie-consent-title">
          Cookies
        </h2>
        <p id="cookie-consent-desc" className="cookie-consent-text">
          We use essential cookies to keep you signed in and to secure GitHub sign-in. See our{" "}
          <Link href="/privacy" className="cookie-consent-link">
            Privacy Policy
          </Link>{" "}
          for details.
        </p>
        <div className="cookie-consent-actions">
          <button type="button" className="button button-primary cookie-consent-accept" onClick={handleAccept}>
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}
