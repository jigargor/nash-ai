import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewPipeline } from "@/components/review/action-chain";
import type { ReviewModelAudit } from "@/lib/api/reviews";

function makeAudit(overrides?: Partial<ReviewModelAudit>): ReviewModelAudit {
  return {
    id: 1,
    run_id: "run-1",
    stage: "primary",
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    prompt_version: "v1",
    input_tokens: 100,
    output_tokens: 50,
    total_tokens: 150,
    findings_count: 3,
    accepted_findings_count: 2,
    conflict_score: null,
    decision: "generated",
    stage_duration_ms: 1200,
    metadata_json: null,
    created_at: "2026-04-28T22:00:00.000Z",
    ...overrides,
  };
}

describe("ReviewPipeline", () => {
  it("shows reset bottom-panel values while a rerun is in progress", () => {
    render(
      <ReviewPipeline
        audits={[]}
        debugArtifacts={null}
        isInFlight
        costUsd={null}
        postedFindingsCount={0}
        pipelineStagedFindingsPeak={0}
      />,
    );

    expect(screen.getByText("Current pipeline step")).toBeInTheDocument();
    expect(screen.getAllByText((_, node) => node?.textContent?.includes("Start: —") ?? false).length).toBeGreaterThan(0);
    expect(screen.getAllByText((_, node) => node?.textContent?.includes("Nodes: 0") ?? false).length).toBeGreaterThan(0);
  });

  it("resets bottom fields when run audits clear", () => {
    const { rerender } = render(
      <ReviewPipeline
        audits={[makeAudit()]}
        debugArtifacts={null}
        isInFlight={false}
        costUsd="0.123456"
        postedFindingsCount={2}
        pipelineStagedFindingsPeak={3}
      />,
    );

    expect(screen.getAllByText((_, node) => node?.textContent?.includes("Nodes: 1") ?? false).length).toBeGreaterThan(0);

    rerender(
      <ReviewPipeline
        audits={[]}
        debugArtifacts={null}
        isInFlight
        costUsd={null}
        postedFindingsCount={0}
        pipelineStagedFindingsPeak={0}
      />,
    );

    expect(screen.getAllByText((_, node) => node?.textContent?.includes("Start: —") ?? false).length).toBeGreaterThan(0);
    expect(screen.getAllByText((_, node) => node?.textContent?.includes("Nodes: 0") ?? false).length).toBeGreaterThan(0);
  });

  it("renders fast-path risk labels separately from reviewed files", () => {
    const { container } = render(
      <ReviewPipeline
        audits={[
          makeAudit({
            stage: "fast_path",
            decision: "full_review",
            findings_count: 0,
            metadata_json: {
              decision: "full_review",
              confidence: null,
              reason: "Escalated for safety",
              risk_labels: ["missing_confidence"],
              review_surface_paths: ["apps/web/next.config.ts"],
              review_surface_count: 1,
              file_classes: { config_only: 1 },
              produces_findings: false,
            },
          }),
        ]}
        debugArtifacts={null}
        isInFlight={false}
        costUsd={null}
        postedFindingsCount={0}
        pipelineStagedFindingsPeak={0}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /fast-path scan/i }));

    const scoped = within(container);
    expect(scoped.getByText("missing_confidence")).toBeInTheDocument();
    expect(scoped.getAllByText("config_only:").length).toBeGreaterThan(0);
    expect(
      scoped.getAllByText((_, node) => node?.textContent?.includes("files reviewed: 1") ?? false).length,
    ).toBeGreaterThan(0);
    expect(scoped.getByText("findings: N/A")).toBeInTheDocument();
  });

  it("does not mark HTTP 200 red when fast-path rationale mentions error handling", () => {
    render(
      <ReviewPipeline
        audits={[
          makeAudit({
            stage: "fast_path",
            decision: "full_review",
            findings_count: 0,
            metadata_json: {
              decision: "full_review",
              confidence: 90,
              reason: "PR includes error handling and webhooks.",
              risk_labels: ["webhooks"],
              review_surface_paths: [],
              review_surface_count: 0,
              file_classes: {},
              produces_findings: false,
            },
          }),
        ]}
        debugArtifacts={null}
        isInFlight={false}
        costUsd={null}
        postedFindingsCount={0}
        pipelineStagedFindingsPeak={0}
      />,
    );

    const fastPathButtons = screen.getAllByRole("button", { name: /fast-path scan/i });
    for (const fastPathButton of fastPathButtons) {
      const status200 = within(fastPathButton).getByText("200");
      expect(status200).toHaveAttribute("title", "Successful stage response");
    }
  });
});
