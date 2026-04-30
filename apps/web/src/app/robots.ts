import type { MetadataRoute } from "next";

import { getSiteUrl } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  const siteUrl = getSiteUrl();
  const sitemapUrl = new URL("/sitemap.xml", siteUrl).toString();

  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/about", "/privacy", "/terms"],
        disallow: ["/dashboard", "/repos", "/reviews", "/settings", "/code-tour", "/api"],
      },
    ],
    sitemap: sitemapUrl,
  };
}
