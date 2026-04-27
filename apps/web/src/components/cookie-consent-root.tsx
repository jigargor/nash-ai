"use client";

import dynamic from "next/dynamic";

const CookieConsentBanner = dynamic(
  () => import("@/components/cookie-consent-banner").then((m) => m.CookieConsentBanner),
  { ssr: false },
);

export function CookieConsentRoot() {
  return <CookieConsentBanner />;
}
