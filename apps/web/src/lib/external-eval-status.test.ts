import { describe, expect, it } from "vitest";

import { hasNonTerminalExternalEval, isExternalEvalTerminalStatus } from "@/lib/external-eval-status";

describe("external eval status polling gate", () => {
  it("classifies terminal statuses", () => {
    for (const status of ["complete", "failed", "partial", "canceled"])
      expect(isExternalEvalTerminalStatus(status)).toBe(true);
    for (const status of ["queued", "running", "synthesizing"])
      expect(isExternalEvalTerminalStatus(status)).toBe(false);
    expect(isExternalEvalTerminalStatus(undefined)).toBe(false);
  });

  it("polls only while a row is non-terminal", () => {
    expect(hasNonTerminalExternalEval(undefined)).toBe(false);
    expect(hasNonTerminalExternalEval([])).toBe(false);
    expect(hasNonTerminalExternalEval([{ status: "complete" }, { status: "failed" }])).toBe(false);
    expect(hasNonTerminalExternalEval([{ status: "complete" }, { status: "running" }])).toBe(true);
  });
});
