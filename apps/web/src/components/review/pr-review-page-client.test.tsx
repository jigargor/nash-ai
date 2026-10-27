import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";

import { PrReviewPageClient } from "@/components/review/pr-review-page-client";
import { useReviewUiStore } from "@/stores/review-ui-store";

const rerunState = {
  isPending: false,
};
const forceRecoverState = {
  isPending: false,
};

const reviewState: { status: string; debugArtifacts: Record<string, unknown> | null } = {
  status: "done",
  debugArtifacts: null,
};
const useReviewStreamMock = vi.fn((_reviewId: number, _installationId: number, _options?: { enabled?: boolean }) => ({
  events: [],
  connectionState: "connected",
}));

const useReviewMock = vi.fn(
  (_reviewId: number, _installationId: number, _options?: { enabled?: boolean }) => ({
  isLoading: false,
  isError: false,
  data: {
    id: 1,
    status: reviewState.status,
    debug_artifacts: reviewState.debugArtifacts,
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
          target_line_content: "a = 0",
          patch_hunk: "@@ -1 +1 @@",
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
  useReviewStream: (reviewId: number, installationId: number, options?: { enabled?: boolean }) =>
    useReviewStreamMock(reviewId, installationId, options),
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
  useForceRecoverReview: () => ({
    mutate: vi.fn(),
    isPending: forceRecoverState.isPending,
    isError: false,
    error: null,
  }),
  useDismissFinding: () => ({
    mutateAsync: vi.fn(),
  }),
}));

describe("PrReviewPageClient", () => {
  beforeEach(() => {
    rerunState.isPending = false;
    forceRecoverState.isPending = false;
    reviewState.status = "done";
    reviewState.debugArtifacts = null;
    useReviewStreamMock.mockClear();
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

  it("ignores j/k while typing in an input", () => {
    render(
      <>
        <input aria-label="search" />
        <PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />
      </>,
    );

    fireEvent.keyDown(screen.getByLabelText("search"), { key: "j" });

    expect(useReviewUiStore.getState().selectedFindingIndex).toBe(0);
  });

  it("hides dismissed findings by default and reveals them with a badge when toggled", () => {
    reviewState.debugArtifacts = { dismissed_findings: [0] };
    const { container } = render(
      <PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />,
    );
    const scoped = within(container);

    expect(scoped.queryAllByText("first")).toHaveLength(0);
    expect(scoped.getAllByText("second").length).toBeGreaterThan(0);
    expect(scoped.queryAllByText("DISMISSED")).toHaveLength(0);

    fireEvent.click(scoped.getByRole("button", { name: /Show dismissed \(1\)/ }));

    expect(scoped.getAllByText("first").length).toBeGreaterThan(0);
    expect(scoped.getAllByText("DISMISSED")).toHaveLength(1);
  });

  it("enables the review stream only while the review is in flight", () => {
    render(<PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />);
    expect(useReviewStreamMock.mock.calls.at(-1)?.[2]).toEqual({ enabled: false });

    cleanup();
    useReviewStreamMock.mockClear();
    reviewState.status = "running";
    render(<PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />);
    expect(useReviewStreamMock.mock.calls.at(-1)?.[2]).toEqual({ enabled: true });
  });

  it("renders target line content and severity in the diff viewer placeholder", () => {
    const { container } = render(
      <PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />,
    );
    const scoped = within(container);
    expect(scoped.getAllByText("HIGH").length).toBeGreaterThan(0);
    expect(scoped.getByLabelText("Target line content").textContent).toBe("a = 0");
    expect(scoped.getByLabelText("Patch hunk").textContent).toBe("@@ -1 +1 @@");
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

  it("loads review data immediately when Turnstile site key is set", () => {
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY = "test-site-key";
    render(<PrReviewPageClient owner="acme" repo="repo" prNumber="1" reviewId={1} installationId={10} />);

    const lastReviewOpts = useReviewMock.mock.calls.filter((c) => c[0] === 1 && c[1] === 10).at(-1)?.[2];
    const lastAuditsOpts = useReviewModelAuditsMock.mock.calls.filter((c) => c[0] === 1 && c[1] === 10).at(-1)?.[2];
    expect(lastReviewOpts).toBeUndefined();
    expect(lastAuditsOpts).toBeUndefined();
    expect(screen.getAllByRole("button", { name: /Re-run review/i }).length).toBeGreaterThan(0);
  });
});
