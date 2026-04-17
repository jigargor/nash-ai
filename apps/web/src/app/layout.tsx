import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Code Review",
  description: "Automated PR review powered by Claude",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
