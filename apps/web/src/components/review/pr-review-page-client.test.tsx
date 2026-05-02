import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";

import { PrReviewPageClient } from "@/components/review/pr-review-page-client";
import { useReviewUiStore } from "@/stores/review-ui-store";

const rerunState = {
  isPending: false,
};

const useReviewMock = vi.fn(
  (_reviewId: number, _installationId: number, _options?: { enabled?: boolean }) => ({
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
}));
const useReviewModelAuditsMock = vi.fn(
  (_reviewId: number, _installationId: number, _options?: { enabled?: boolean }) => ({
  data: {
    model_audits: [],
  },
  isLoading: false,
  isError: false,
}));

vi.mock("next/link", () => ({
  default: (props: React.ComponentProps<"a"> & { href: string }) => {
    const { href, children, ...rest } = props;
    return (
      <a href={href} {...rest}>
        {children}
      </a>
    );
  },
}));

vi.mock("@/hooks/use-review", () => ({
  useReview: (reviewId: number, installationId: number, options?: { enabled?: boolean }) =>
    useReviewMock(reviewId, installationId, options),
}));

vi.mock("@/hooks/use-review-stream", () => ({
  useReviewStream: () => ({
    events: [],
    connectionState: "connected",
  }),
}));

vi.mock("@/hooks/use-review-model-audits", () => ({
  useReviewModelAudits: (reviewId: number, installationId: number, options?: { enabled?: boolean }) =>
    useReviewModelAuditsMock(reviewId, installationId, options),
}));

vi.mock("@/hooks/use-review-actions", () => ({
  useRerunReview: () => ({
    mutate: vi.fn(),
    isPending: rerunState.isPending,
  }),
  useDismissFinding: () => ({
    mutateAsync: vi.fn(),
  }),
}));

vi.mock("@/components/security/turnstile-widget", () => ({
  TurnstileWidget: ({ onToken }: { onToken: (token: string) => void }) => (
    <button type="button" onClick={() => onToken("test-token")}>
      Complete mock verification
    </button>
  ),
}));

describe("PrReviewPageClient", () => {
  beforeEach(() => {
    rerunState.isPending = false;
    useReviewMock.mockClear();
    useReviewModelAuditsMock.mockClear();
    delete process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
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

  it("hides findings workspace while rerun is pending", () => {
    rerunState.isPending = true;
    const { container } = render(
      <PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />,
    );
    const scoped = within(container);

    expect(scoped.queryAllByText("first")).toHaveLength(0);
    expect(scoped.queryAllByText("second")).toHaveLength(0);
  });

  it("loads review data when Turnstile site key is set (Turnstile is login-only)", () => {
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY = "test-site-key";
    render(<PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />);

    expect(useReviewMock).toHaveBeenCalledWith(1, 10, undefined);
    expect(useReviewModelAuditsMock).toHaveBeenCalledWith(1, 10, undefined);
    expect(screen.getAllByRole("button", { name: /Re-run review/i }).length).toBeGreaterThan(0);
  });
});
