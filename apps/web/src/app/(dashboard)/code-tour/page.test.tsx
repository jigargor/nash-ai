import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";

import CodeTourPage from "@/app/(dashboard)/code-tour/page";

vi.mock("@/components/review/external-eval-action-chain", () => ({
  ExternalEvalActionChain: () => <div data-testid="external-eval-action-chain" />,
}));

const estimateState: { data: { estimated_cost_usd: string; warning: string; owner: string; repo: string; target_ref: string; file_count: number; estimated_tokens: number } | null } = {
  data: null,
};

vi.mock("@/hooks/use-installations", () => ({
  useInstallations: () => ({
    data: [
      { installation_id: 101, account_login: "first-org", active: true },
      { installation_id: 202, account_login: "second-org", active: true },
    ],
  }),
}));

vi.mock("@/hooks/use-external-evals", () => ({
  useExternalEvalEstimate: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    data: estimateState.data,
    error: null,
  }),
  useCreateExternalEval: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
  useCancelExternalEval: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
  useExternalEvals: () => ({
    isLoading: false,
    isError: false,
    data: [],
    error: null,
  }),
  useExternalEvalDetail: () => ({
    isLoading: false,
    isError: false,
    data: null,
    error: null,
  }),
}));

afterEach(() => {
  estimateState.data = null;
  cleanup();
});

describe("CodeTourPage", () => {
  it("defaults installation selector to first active installation", async () => {
    render(<CodeTourPage />);

    const installationSelect = screen.getByRole("combobox");
    await waitFor(() => {
      expect(installationSelect).toHaveValue("101");
    });
  });

  it("renders branch and estimate info tooltips", () => {
    estimateState.data = {
      estimated_cost_usd: "1.250000",
      warning: "example warning",
      owner: "acme",
      repo: "repo",
      target_ref: "main",
      file_count: 42,
      estimated_tokens: 12000,
    };
    render(<CodeTourPage />);

    expect(
      screen.getByTitle("If omitted, we analyze the repository's default branch."),
    ).toBeInTheDocument();
    expect(
      screen.getByTitle(
        "Estimate uses repository file count and total bytes, then converts bytes to token estimates and applies current pricing assumptions. Final cost may vary.",
      ),
    ).toBeInTheDocument();
  });

  it("blocks actions and shows validation for invalid budget", async () => {
    render(<CodeTourPage />);

    const repoInput = screen.getByPlaceholderText("https://github.com/owner/repo");
    fireEvent.change(repoInput, { target: { value: "https://github.com/acme/repo" } });

    const tokenInput = screen.getByDisplayValue("2000000");
    fireEvent.change(tokenInput, { target: { value: "9000" } });

    expect(screen.getByText("Token budget cap must be between 10,000 and 30,000,000.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Estimate Cost" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start Evaluation" })).toBeDisabled();
  });
});
