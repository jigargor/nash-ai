import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { StaticDocument } from "@/components/layout/static-document";
import { buildSeoMetadata } from "@/lib/seo";

const GITHUB_REPO_URL = "https://github.com/jigargor/nash-ai";
const GITHUB_PROFILE_URL = "https://github.com/jigargor";

export const metadata: Metadata = buildSeoMetadata({
  title: "About Nash AI",
  description:
    "Learn what Nash AI is, how agentic pull request reviews work, and why teams use it to improve code review quality and speed.",
  path: "/about",
  keywords: ["AI code review", "agentic pull request review", "GitHub App code review"],
});

export default function AboutPage() {
  return (
    <main className="static-document-shell">
      <StaticDocument
        title="About Nash AI"
        description="Nash AI is an agentic GitHub pull request review app focused on actionable findings, practical suggestions, and faster engineering feedback loops."
      >
        <h2 className="static-document-h2">What Nash AI helps teams do</h2>
        <p>
          Nash AI is a GitHub App that runs tool-augmented agents over your pull requests: it reads diffs and
          repository context, reasons with one or more large language models, and posts inline review comments
          (including suggested fixes where appropriate). Repository behavior can be tuned with a{" "}
          <code className="static-document-code">.codereview.yml</code> so you can experiment with providers,
          budgets, and review policies per repo.
        </p>
        <h2 className="static-document-h2">How review workflows stay practical</h2>
        <p>
          The project doubled as a way to <strong>compare and contrast models</strong>—how they trade off
          thoroughness, tone, false positives, and tool use—while still aiming to build something genuinely useful
          for day-to-day review workflows, whether for me or for anyone else who finds it helpful.
        </p>
        <h2 className="static-document-h2">Source and policy links</h2>
        <p>
          Source code and issue tracking live on GitHub:{" "}
          <a href={GITHUB_REPO_URL} target="_blank" rel="noopener noreferrer">
            {GITHUB_REPO_URL}
          </a>{" "}
          (MIT License).
        </p>
        <p>
          For governance and legal details, review our{" "}
          <Link href="/privacy">Privacy Policy</Link> and{" "}
          <Link href="/terms">Terms and Conditions</Link>.
        </p>

        <hr className="static-document-rule" />

        <section className="static-document-bio-wrap" aria-label="Author note">
          <Image
            src="/me.png"
            alt=""
            width={112}
            height={112}
            className="static-document-bio-thumb"
            sizes="112px"
          />
          <div className="static-document-bio">
            <p>
              Hi, I&apos;m{" "}
              <a href={GITHUB_PROFILE_URL} target="_blank" rel="noopener noreferrer">
                Jigar
              </a>
              . I have some professional experience working as a full-stack engineer with a background in clinical
              data systems and a deep curiosity about what AI can do when it&apos;s built carefully. Nash AI started
              as a personal tool—I wanted to compare, contrast, and utilize interactions between different models,
              multiple agents and so on. So I built it.
            </p>
            <p>
              I spent six years building data pipelines and LLM-integrated systems in healthcare, took a deliberate
              sabbatical to reorient, and came back building things I actually want to exist. Nash AI is one of them.
            </p>
            <p>
              When I&apos;m not coding I&apos;m lifting, baking, hiking, or reading something that has nothing to do
              with software.
            </p>
          </div>
        </section>
      </StaticDocument>
    </main>
  );
}
