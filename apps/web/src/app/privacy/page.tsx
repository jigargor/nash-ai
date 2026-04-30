import type { Metadata } from "next";
import Link from "next/link";

import { StaticDocument } from "@/components/layout/static-document";
import { buildSeoMetadata } from "@/lib/seo";

export const metadata: Metadata = buildSeoMetadata({
  title: "Privacy Policy",
  description:
    "Read the Nash AI privacy policy covering data categories, subprocessors, retention, and security practices for AI-assisted code review workflows.",
  path: "/privacy",
});

export default function PrivacyPage() {
  return (
    <main className="static-document-shell">
      <StaticDocument
        title="Privacy Policy"
        description="Last updated: April 27, 2026. This describes typical data practices for Nash AI as an agentic code review service integrated with GitHub and third-party model providers. You can replace or refine this text as your deployment matures."
      >
        <h2 className="static-document-h2">Overview</h2>
        <p>
          Nash AI provides automated pull request reviews using AI models and the GitHub platform. This policy
          summarizes the categories of information involved, why they are processed, and the safeguards that align
          with common expectations for developer tools. It is not legal advice; adapt it for your jurisdiction,
          customers, and subprocessors.
        </p>

        <h2 className="static-document-h2">Information we process</h2>
        <p>Depending on how you use the service, processing may include:</p>
        <ul className="static-document-list">
          <li>
            <strong>Account and session data</strong> when you sign in to the dashboard (for example GitHub OAuth
            profile identifiers we receive from GitHub, and an httpOnly session cookie used to keep you signed in).
          </li>
          <li>
            <strong>Repository and pull request metadata</strong> such as owner, repository name, pull request
            number, branch names, and commit SHAs needed to run reviews.
          </li>
          <li>
            <strong>Code and diff content</strong> from pull requests and related files that the review agent loads
            as context to produce findings.
          </li>
          <li>
            <strong>Review outputs</strong> including generated findings, severities, suggested edits, and related
            metadata stored to operate the product.
          </li>
          <li>
            <strong>Operational telemetry</strong> if enabled in your deployment (for example error reporting or
            model tracing), which may include technical diagnostics and high-level usage metadata—not passwords or
            raw API keys.
          </li>
        </ul>

        <h2 className="static-document-h2">How we use information</h2>
        <p>We use the above categories to:</p>
        <ul className="static-document-list">
          <li>Provide, operate, and secure the review service and dashboard;</li>
          <li>Authenticate users and enforce rate limits or abuse protections;</li>
          <li>Maintain audit trails needed for debugging and compliance (for example model or token metadata);</li>
          <li>Improve reliability and safety of the product (without using your code to train public models unless
            you separately configure providers that do so and disclose that clearly).</li>
        </ul>

        <h2 className="static-document-h2">Third parties and subprocessors</h2>
        <p>
          The service relies on integrations you enable. Typical subprocessors include <strong>GitHub</strong> (source
          control, webhooks, and review comments) and one or more <strong>LLM providers</strong> (for example
          Anthropic, OpenAI, or Google) that receive prompts containing review context. Optional observability tools
          (such as Sentry or Langfuse-style tracing) may process error or trace data. Each provider has its own
          privacy policy; using Nash AI means their processing may occur on your behalf to deliver the service.
        </p>

        <h2 className="static-document-h2">Retention</h2>
        <p>
          Retention periods should match your operational needs. Many teams retain review artifacts for a bounded
          window (for example on the order of 90 days) and delete or archive older data. Configure backups and
          deletion workflows consistent with your agreements and regulations.
        </p>

        <h2 className="static-document-h2">Cookie preference banner</h2>
        <p>
          If shown, the in-app cookie notice sets a browser cookie (
          <code className="static-document-code">nash_cookie_consent</code>) for up to one year so we do not
          repeat the prompt on every visit. It records that you acknowledged how we use essential cookies, as
          described here.
        </p>

        <h2 className="static-document-h2">Security</h2>
        <p>
          Reasonable measures include encrypted transport (HTTPS), protecting long-lived secrets and tokens, avoiding
          logging sensitive values, validating webhooks, and limiting access to production data. Self-hosted operators
          remain responsible for their infrastructure hardening and access control.
        </p>

        <h2 className="static-document-h2">International transfers</h2>
        <p>
          If you or your subprocessors process data across borders, ensure appropriate safeguards (such as standard
          contractual clauses) are in place and documented for your organization.
        </p>

        <h2 className="static-document-h2">Your rights</h2>
        <p>
          Depending on where you live, you may have rights to access, correct, export, or delete personal data
          associated with your account, or to object to certain processing. Contact the operator of your Nash AI
          deployment to exercise those rights. If you use GitHub OAuth, you can also revoke the application from your
          GitHub settings, which stops new access through that authorization path.
        </p>

        <h2 className="static-document-h2">Children</h2>
        <p>The service is intended for professional developers and is not directed at children.</p>

        <h2 className="static-document-h2">Changes</h2>
        <p>
          We may update this policy as the product evolves. Material changes should be communicated through your usual
          channels (for example release notes or in-app notice).
        </p>

        <h2 className="static-document-h2">Contact</h2>
        <p>
          For privacy questions about a specific deployment, contact the maintainer or organization operating that
          instance. For the open-source project, use the repository&apos;s issue tracker or maintainer contact on{" "}
          <a href="https://github.com/jigargor/nash-ai" target="_blank" rel="noopener noreferrer">
            GitHub
          </a>
          .
        </p>
        <p>
          Need overall product context first? Start with the <Link href="/about">About Nash AI</Link> page. Terms
          governing service use are in <Link href="/terms">Terms and Conditions</Link>.
        </p>
      </StaticDocument>
    </main>
  );
}
