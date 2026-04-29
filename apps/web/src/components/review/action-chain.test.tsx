import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActionChain } from "@/components/review/action-chain";
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

describe("ActionChain", () => {
  it("shows reset bottom-panel values while a rerun is in progress", () => {
    render(
      <ActionChain
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
      <ActionChain
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
      <ActionChain
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
});
