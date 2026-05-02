import Image from "next/image";
import Link from "next/link";
import type { Metadata } from "next";

import { LoginTurnstileForm } from "@/components/security/login-turnstile-form";
import { logoPngSrc } from "@/lib/branding";
import { buildSeoMetadata } from "@/lib/seo";

interface LoginPageProps {
  searchParams: Promise<{ error?: string }>;
}

export const metadata: Metadata = buildSeoMetadata({
  title: "Login",
  description: "Sign in to Nash AI with GitHub to access your review dashboard.",
  path: "/login",
  noindex: true,
});

function errorMessage(code: string | undefined): string | null {
  if (!code) return null;
  if (code === "state_mismatch") return "Sign-in session expired. Please try again.";
  if (code === "pkce_mismatch") return "Sign-in verification failed. Please try again.";
  if (code === "oauth_failed") return "GitHub sign-in failed. Please try again.";
  if (code === "turnstile_failed") return "Security verification failed. Please complete the challenge again.";
  return "Something went wrong. Please try again.";
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const sp = await searchParams;
  const err = errorMessage(sp.error);

  return (
    <main className="login-page">
      <section className="login-card">
        <div className="login-logo-wrap">
          <Image
            src={logoPngSrc()}
            alt="Nash AI logo"
            width={200}
            height={200}
            priority
            className="login-logo"
          />
        </div>
        <h1 className="login-title">Sign in</h1>
        <p className="login-lead">Authenticate with your GitHub account to access the review dashboard.</p>

        {err ? (
          <p className="login-error" role="alert">
            {err}
          </p>
        ) : null}

        <p className="login-lead" style={{ margin: 0, fontSize: "0.86rem" }}>
          By continuing, you may be prompted to accept our{" "}
          <Link href="/terms" className="login-inline-link">
            Terms & Conditions
          </Link>{" "}
          if this is your first sign-in or the terms changed.
        </p>
        <LoginTurnstileForm />
      </section>
    </main>
  );
}
