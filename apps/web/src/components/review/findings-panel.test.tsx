import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, beforeEach } from "vitest";
import React from "react";

import { FindingsPanel } from "@/components/review/findings-panel";
import { useReviewUiStore } from "@/stores/review-ui-store";

const findings = [
  {
    severity: "high",
    category: "security",
    message: "High severity issue",
    file_path: "a.py",
    line_start: 10,
    line_end: 10,
    suggestion: "print('fixed')",
    confidence: 90,
    evidence: "diff_visible",
  },
  {
    severity: "low",
    category: "style",
    message: "Low severity issue",
    file_path: "b.py",
    line_start: 2,
    line_end: 2,
    suggestion: undefined,
    confidence: 80,
    evidence: "diff_visible",
  },
] as const;

describe("FindingsPanel", () => {
  beforeEach(() => {
    useReviewUiStore.setState({
      selectedFindingIndex: null,
      severityFilters: {},
      categoryFilters: {},
      expandedFiles: {},
    });
  });

  it("filters by selected severity pill", () => {
    render(
      <FindingsPanel
        findings={[...findings]}
        findingOutcomes={[]}
        selectedFindingIndex={null}
        onSelectFinding={() => undefined}
        onDismiss={() => undefined}
        onCopySuggestion={() => undefined}
      />,
    );

    expect(screen.getByText("High severity issue")).toBeInTheDocument();
    expect(screen.getByText("Low severity issue")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "high" }));

    expect(screen.getByText("High severity issue")).toBeInTheDocument();
    expect(screen.queryByText("Low severity issue")).not.toBeInTheDocument();
  });
});
