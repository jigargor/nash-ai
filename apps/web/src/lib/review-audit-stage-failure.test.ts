import { describe, expect, it } from "vitest";

import { doesAuditReasonTextSuggestStageFailure } from "@/lib/review-audit-stage-failure";

describe("doesAuditReasonTextSuggestStageFailure", () => {
  it("returns false for empty or missing reason", () => {
    expect(doesAuditReasonTextSuggestStageFailure(undefined)).toBe(false);
    expect(doesAuditReasonTextSuggestStageFailure("")).toBe(false);
  });

  it("returns false when rationale mentions error handling without failure wording", () => {
    expect(doesAuditReasonTextSuggestStageFailure("PR includes error handling and webhooks.")).toBe(false);
  });

  it("returns true when reason explicitly indicates failure", () => {
    expect(doesAuditReasonTextSuggestStageFailure("Provider call failed with timeout.")).toBe(true);
  });
});
