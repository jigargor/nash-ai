import Image from "next/image";
import Link from "next/link";

import { logoPngSrc } from "@/lib/branding";

interface LoginPageProps {
  searchParams: Promise<{ error?: string }>;
}

function errorMessage(code: string | undefined): string | null {
  if (!code) return null;
  if (code === "terms" || code === "terms_required") {
    return "Please accept the Terms & Conditions to continue.";
  }
  if (code === "state_mismatch") return "Sign-in session expired. Please try again.";
  if (code === "pkce_mismatch") return "Sign-in verification failed. Please try again.";
  if (code === "oauth_failed") return "GitHub sign-in failed. Please try again.";
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

        <form action="/api/v1/auth/login" method="post" className="login-form">
          <label className="login-terms-label">
            <input type="checkbox" name="accept_terms" value="on" required className="login-terms-checkbox" />
            <span>
              I have read and agree to the{" "}
              <Link href="/terms" className="login-inline-link">
                Terms & Conditions
              </Link>
              .
            </span>
          </label>
          <button type="submit" className="button button-primary login-submit">
            Continue with GitHub
          </button>
        </form>
      </section>
    </main>
  );
}
