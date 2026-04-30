import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import React from "react";

import ReviewsPage from "@/app/(dashboard)/reviews/page";

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

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () =>
    new URLSearchParams({
      q: "",
    }),
}));

vi.mock("@/hooks/use-installations", () => ({
  useInstallations: () => ({
    data: [],
  }),
}));

vi.mock("@/hooks/use-reviews", () => ({
  useReviews: () => ({
    isLoading: false,
    isError: false,
    data: [
      {
        id: 1,
        installation_id: 99,
        repo_full_name: "acme/repo",
        pr_number: 1,
        status: "done",
        findings_count: 0,
        cost_usd: "0.010000",
      },
    ],
  }),
}));

describe("ReviewsPage", () => {
  it("always includes running and skipped status options", () => {
    render(<ReviewsPage />);
    expect(screen.getByRole("option", { name: "done" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "failed" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "running" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "skipped" })).toBeInTheDocument();
  });
});
