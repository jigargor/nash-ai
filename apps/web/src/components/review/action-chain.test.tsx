import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ActionChain } from "@/components/review/action-chain";
import type { ReviewModelAudit } from "@/lib/api/reviews";

function buildAudit(overrides: Partial<ReviewModelAudit>): ReviewModelAudit {
  return {
    id: 1,
    run_id: "run-1",
    stage: "editor",
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    prompt_version: "test",
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    findings_count: 0,
    accepted_findings_count: 0,
    conflict_score: null,
    decision: "skipped",
    stage_duration_ms: null,
    metadata_json: { reason: "no_findings_to_edit" },
    created_at: null,
    ...overrides,
  };
}

describe("ActionChain editor states", () => {
  it("shows explicit skipped editor message", async () => {
    render(<ActionChain audits={[buildAudit({})]} debugArtifacts={{}} postedFindingsCount={0} />);
    await userEvent.click(screen.getByRole("button", { name: /Editor pass/i }));
    expect(screen.getByText(/Editor pass skipped/i)).toBeInTheDocument();
  });

  it("shows explicit no-action editor message", async () => {
    render(
      <ActionChain
        audits={[
          buildAudit({
            decision: "edited",
            metadata_json: { keep_count: 0, drop_count: 0, modify_count: 0 },
          }),
        ]}
        debugArtifacts={{}}
        postedFindingsCount={0}
      />
    );
    const editedBadge = screen.getByText("edited");
    const button = editedBadge.closest("button");
    if (!button) throw new Error("expected editor stage button");
    await userEvent.click(button);
    expect(screen.getByText(/no keep\/modify\/drop actions/i)).toBeInTheDocument();
  });
});
