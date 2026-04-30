import type { Metadata } from "next";
import { Inter, Instrument_Serif, Roboto_Mono } from "next/font/google";

import { CookieConsentRoot } from "@/components/cookie-consent-root";
import { SiteBottomNav } from "@/components/layout/site-bottom-nav";
import { WebVitalsReporter } from "@/components/telemetry/web-vitals-reporter";
import { logoPngSrc } from "@/lib/branding";
import { absoluteUrl, getSiteUrl } from "@/lib/seo";

import "./globals.css";

const geistSans = Inter({ subsets: ["latin"], variable: "--font-geist-sans", display: "swap" });
const geistMono = Roboto_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
  preload: false,
});
const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-instrument-serif",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  metadataBase: getSiteUrl(),
  title: {
    default: "Nash AI | Agentic Pull Request Reviews",
    template: "%s | Nash AI",
  },
  description:
    "Nash AI helps engineering teams run agentic pull request reviews with actionable, line-level findings and safer merge decisions.",
  alternates: {
    canonical: absoluteUrl("/about"),
  },
  openGraph: {
    title: "Nash AI | Agentic Pull Request Reviews",
    description:
      "Automate pull request review workflows with agentic analysis, evidence-backed findings, and practical fix suggestions.",
    url: absoluteUrl("/about"),
    siteName: "Nash AI",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Nash AI | Agentic Pull Request Reviews",
    description:
      "Automated pull request reviews with agentic workflows, inline findings, and reproducible remediation guidance.",
  },
  icons: {
    icon: logoPngSrc(),
    shortcut: logoPngSrc(),
    apple: logoPngSrc(),
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable}`}
        suppressHydrationWarning
      >
        <div className="site-root">{children}</div>
        <SiteBottomNav />
        <CookieConsentRoot />
        <WebVitalsReporter />
      </body>
    </html>
  );
}
