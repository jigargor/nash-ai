/** Client-readable cookie (not httpOnly) so the banner can hide without a round trip. */
export const COOKIE_CONSENT_COOKIE_NAME = "nash_cookie_consent";

/** One year in seconds. */
export const COOKIE_CONSENT_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

export function buildCookieConsentCookieValue(): string {
  return "1";
}
