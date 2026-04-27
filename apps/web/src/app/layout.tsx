import type { Metadata } from "next";
import { Inter, Instrument_Serif, Roboto_Mono } from "next/font/google";

import { CookieConsentRoot } from "@/components/cookie-consent-root";
import { SiteBottomNav } from "@/components/layout/site-bottom-nav";
import { logoPngSrc } from "@/lib/branding";

import "./globals.css";

const geistSans = Inter({ subsets: ["latin"], variable: "--font-geist-sans" });
const geistMono = Roboto_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-instrument-serif",
});

export const metadata: Metadata = {
  title: "AI Code Review",
  description: "Automated PR review powered by Claude",
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
      </body>
    </html>
  );
}
