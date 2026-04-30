import type { Metadata } from "next";

interface SeoMetadataInput {
  title: string;
  description: string;
  path: string;
  keywords?: string[];
  noindex?: boolean;
}

const DEFAULT_SITE_URL = "http://localhost:3000";

function trimTrailingSlash(value: string): string {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

function normalizePath(pathname: string): string {
  if (!pathname || pathname === "/") return "/";
  return pathname.startsWith("/") ? pathname : `/${pathname}`;
}

export function getSiteUrl(): URL {
  const raw = process.env.NEXT_PUBLIC_WEB_APP_URL ?? process.env.WEB_APP_URL ?? DEFAULT_SITE_URL;
  try {
    return new URL(trimTrailingSlash(raw));
  } catch {
    return new URL(DEFAULT_SITE_URL);
  }
}

export function absoluteUrl(pathname: string): string {
  const baseUrl = getSiteUrl();
  const normalizedPath = normalizePath(pathname);
  return new URL(normalizedPath, baseUrl).toString();
}

export function buildSeoMetadata(input: SeoMetadataInput): Metadata {
  const canonical = absoluteUrl(input.path);
  const robots = input.noindex ? { index: false, follow: false } : { index: true, follow: true };

  return {
    title: input.title,
    description: input.description,
    keywords: input.keywords,
    alternates: { canonical },
    openGraph: {
      title: input.title,
      description: input.description,
      type: "website",
      url: canonical,
      siteName: "Nash AI",
    },
    twitter: {
      card: "summary_large_image",
      title: input.title,
      description: input.description,
    },
    robots,
  };
}
