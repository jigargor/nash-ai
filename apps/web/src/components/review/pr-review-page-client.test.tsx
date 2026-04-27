import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";

import { PrReviewPageClient } from "@/components/review/pr-review-page-client";
import { useReviewUiStore } from "@/stores/review-ui-store";

vi.mock("@/hooks/use-review", () => ({
  useReview: () => ({
    isLoading: false,
    isError: false,
    data: {
      id: 1,
      status: "done",
      tokens_used: 123,
      cost_usd: "0.120000",
      findings: {
        summary: "Summary",
        findings: [
          {
            severity: "high",
            category: "security",
            message: "first",
            file_path: "a.py",
            line_start: 1,
            line_end: 1,
            suggestion: "a = 1",
            confidence: 90,
            evidence: "diff_visible",
          },
          {
            severity: "medium",
            category: "correctness",
            message: "second",
            file_path: "b.py",
            line_start: 2,
            line_end: 2,
            suggestion: "b = 2",
            confidence: 80,
            evidence: "diff_visible",
          },
        ],
      },
      finding_outcomes: [],
    },
  }),
}));

vi.mock("@/hooks/use-review-stream", () => ({
  useReviewStream: () => ({
    events: [],
    connectionState: "connected",
  }),
}));

vi.mock("@/hooks/use-review-model-audits", () => ({
  useReviewModelAudits: () => ({
    data: {
      model_audits: [],
    },
    isLoading: false,
    isError: false,
  }),
}));

vi.mock("@/hooks/use-review-actions", () => ({
  useRerunReview: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useDismissFinding: () => ({
    mutateAsync: vi.fn(),
  }),
}));

describe("PrReviewPageClient", () => {
  beforeEach(() => {
    useReviewUiStore.setState({
      selectedFindingIndex: null,
      severityFilters: {},
      categoryFilters: {},
      expandedFiles: {},
    });
  });

  it("updates selected finding with keyboard navigation", () => {
    render(<PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />);

    fireEvent.keyDown(window, { key: "j" });

    expect(useReviewUiStore.getState().selectedFindingIndex).toBe(1);
  });

  it("links finding click to diff selection state", () => {
    render(<PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />);

    fireEvent.click(screen.getAllByText("first")[0]);

    expect(useReviewUiStore.getState().selectedFindingIndex).toBe(0);
  });
});
