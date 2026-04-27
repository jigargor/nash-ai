/** Bump this when replacing `public/logo.png` so favicons and `<Image>` skip stale caches. */
export const LOGO_PNG_VERSION = "2";

export function logoPngSrc(): string {
  return `/logo.png?v=${LOGO_PNG_VERSION}`;
}
