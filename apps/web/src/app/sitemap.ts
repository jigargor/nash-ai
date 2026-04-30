import type { MetadataRoute } from "next";

import { absoluteUrl } from "@/lib/seo";

const PUBLIC_PATHS = ["/about", "/privacy", "/terms"] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  return PUBLIC_PATHS.map((pathname) => ({
    url: absoluteUrl(pathname),
    lastModified,
    changeFrequency: "monthly",
    priority: pathname === "/about" ? 0.8 : 0.4,
  }));
}
