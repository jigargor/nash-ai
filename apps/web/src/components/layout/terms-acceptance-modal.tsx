"use client";

import Link from "next/link";

interface TermsAcceptanceModalProps {
  isSubmitting: boolean;
  onAccept: () => void;
}

export function TermsAcceptanceModal({ isSubmitting, onAccept }: TermsAcceptanceModalProps) {
  return (
    <div className="terms-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="terms-modal-title">
      <section className="terms-modal">
        <header className="terms-modal-header">
          <h2 id="terms-modal-title" className="terms-modal-title">
            Terms & Conditions
          </h2>
          <p className="terms-modal-subtitle">
            Please review and accept the latest terms to continue using Nash AI.
          </p>
        </header>

        <div className="terms-modal-scroll">
          <h3>Agreement</h3>
          <p>
            By using Nash AI, you agree to these terms and confirm you have authority to use connected
            repositories and integrations.
          </p>
          <h3>AI output disclaimer</h3>
          <p>
            Review output is decision-support only. It may be incomplete or incorrect, and you remain
            responsible for validating changes before merge.
          </p>
          <h3>Data processing</h3>
          <p>
            Repository diffs and selected context may be processed by third-party model providers in order to
            produce review results.
          </p>
          <h3>Acceptable use</h3>
          <p>
            Do not use the service to violate legal obligations, misuse credentials, or bypass security
            controls.
          </p>
          <p>
            Read the full legal text here:{" "}
            <Link href="/terms" target="_blank" rel="noopener noreferrer">
              Terms & Conditions
            </Link>
            .
          </p>
        </div>

        <footer className="terms-modal-actions">
          <a href="/api/v1/auth/logout" className="button button-ghost">
            Cancel
          </a>
          <button type="button" className="button button-primary" onClick={onAccept} disabled={isSubmitting}>
            {isSubmitting ? "Saving..." : "I Agree"}
          </button>
        </footer>
      </section>
    </div>
  );
}
