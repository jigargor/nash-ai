// __Host- prefix enforces: Secure flag, Path=/, no Domain attribute.
// Browsers reject cookies that don't satisfy all three — prevents subdomain
// hijacking and ensures the cookie is only transmitted over HTTPS.
// Note: most browsers accept Secure cookies on localhost for dev purposes.
export const AUTH_COOKIE_NAME = "__Host-nash_session";
export const AUTH_STATE_COOKIE_NAME = "__Host-nash_oauth_state";
export const AUTH_PKCE_VERIFIER_COOKIE_NAME = "__Host-nash_oauth_pkce_verifier";
export const AUTH_COOKIE_TTL_SECONDS = 60 * 60 * 24;

/** Set when the user submits the login form with terms accepted; required before OAuth redirect. */
export const TERMS_ACCEPTANCE_COOKIE_NAME = "__Host-nash_terms_accept";
/** Long enough to complete the GitHub OAuth round trip. */
export const TERMS_ACCEPTANCE_COOKIE_TTL_SECONDS = 60 * 15;
