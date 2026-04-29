"use client";

import { useEffect, useMemo, useState } from "react";

import { ExternalEvalActionChain } from "@/components/review/external-eval-action-chain";
import { Panel } from "@/components/ui/panel";
import { StateBlock } from "@/components/ui/state-block";
import {
  useCancelExternalEval,
  useCreateExternalEval,
  useExternalEvalDetail,
  useExternalEvalEstimate,
  useExternalEvals,
} from "@/hooks/use-external-evals";
import { useInstallations } from "@/hooks/use-installations";
import { ApiError } from "@/lib/api/client";

function formatCurrency(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "$0.00";
  return `$${numeric.toFixed(4)}`;
}

function extractApiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Request failed. Please retry.";
  try {
    const parsed = JSON.parse(error.message) as { detail?: string };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) return parsed.detail;
  } catch {
    // Fall back to the raw message below.
  }
  return error.message || `Request failed (${error.status}).`;
}

interface FormErrors {
  repoUrl?: string;
  targetRef?: string;
  tokenBudgetCap?: string;
  costBudgetCapUsd?: string;
}

function validateRepoUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return "Repository URL is required.";
  try {
    const parsed = new URL(trimmed);
    if (parsed.hostname !== "github.com") return "Use a GitHub repository URL.";
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parts.length < 2) return "Use the format https://github.com/owner/repo.";
    return null;
  } catch {
    return "Enter a valid URL (for example: https://github.com/owner/repo).";
  }
}

function validateForm(
  repoUrl: string,
  targetRef: string,
  tokenBudgetCap: number,
  costBudgetCapUsd: number,
): FormErrors {
  const errors: FormErrors = {};
  const repoUrlError = validateRepoUrl(repoUrl);
  if (repoUrlError) errors.repoUrl = repoUrlError;
  if (targetRef.trim().length > 255) errors.targetRef = "Branch / tag / commit must be 255 characters or fewer.";
  if (!Number.isFinite(tokenBudgetCap) || tokenBudgetCap < 10_000 || tokenBudgetCap > 30_000_000) {
    errors.tokenBudgetCap = "Token budget cap must be between 10,000 and 30,000,000.";
  }
  if (!Number.isFinite(costBudgetCapUsd) || costBudgetCapUsd < 0.5 || costBudgetCapUsd > 500) {
    errors.costBudgetCapUsd = "Cost budget cap must be between $0.50 and $500.00.";
  }
  return errors;
}

export default function CodeTourPage() {
  const installations = useInstallations();
  const [selectedInstallationId, setSelectedInstallationId] = useState<number | undefined>(undefined);
  const [repoUrl, setRepoUrl] = useState("");
  const [targetRef, setTargetRef] = useState("");
  const [ackConfirmed, setAckConfirmed] = useState(false);
  const [tokenBudgetCap, setTokenBudgetCap] = useState(2_000_000);
  const [costBudgetCapUsd, setCostBudgetCapUsd] = useState(25);
  const [selectedEvalId, setSelectedEvalId] = useState<number | undefined>(undefined);

  const estimateMutation = useExternalEvalEstimate();
  const createMutation = useCreateExternalEval();
  const cancelMutation = useCancelExternalEval();

  const activeInstallations = useMemo(
    () => installations.data?.filter((item) => item.active) ?? [],
    [installations.data],
  );
  const installationId = useMemo(() => {
    if (activeInstallations.length === 0) return undefined;
    const selectedInstallation = activeInstallations.find(
      (item) => item.installation_id === selectedInstallationId,
    );
    return selectedInstallation?.installation_id ?? activeInstallations[0]?.installation_id;
  }, [activeInstallations, selectedInstallationId]);
  const evalList = useExternalEvals(installationId);
  const evalDetail = useExternalEvalDetail(selectedEvalId, installationId);

  useEffect(() => {
    const rows = evalList.data ?? [];
    if (rows.length === 0) {
      setSelectedEvalId(undefined);
      return;
    }
    if (selectedEvalId == null || !rows.some((row) => row.id === selectedEvalId)) {
      setSelectedEvalId(rows[0].id);
    }
  }, [evalList.data, selectedEvalId]);
  const formErrors = useMemo(
    () => validateForm(repoUrl, targetRef, tokenBudgetCap, costBudgetCapUsd),
    [repoUrl, targetRef, tokenBudgetCap, costBudgetCapUsd],
  );
  const hasFormErrors = Object.keys(formErrors).length > 0;

  const handleEstimate = () => {
    if (!installationId) return;
    estimateMutation.mutate({
      installation_id: installationId,
      repo_url: repoUrl.trim(),
      target_ref: targetRef.trim() || undefined,
    });
  };

  const handleCreate = () => {
    if (!installationId) return;
    createMutation.mutate(
      {
        installation_id: installationId,
        repo_url: repoUrl.trim(),
        target_ref: targetRef.trim() || undefined,
        ack_confirmed: ackConfirmed,
        token_budget_cap: tokenBudgetCap,
        cost_budget_cap_usd: costBudgetCapUsd,
      },
      {
        onSuccess: (result) => {
          setSelectedEvalId(result.external_eval_id);
        },
      },
    );
  };

  return (
    <section style={{ display: "grid", gap: "1rem" }}>
      <Panel elevated>
        <h1 style={{ marginTop: 0, marginBottom: "0.5rem" }}>Code Tour</h1>
        <p style={{ marginTop: 0, color: "var(--text-muted)" }}>
          Analyze an entire public GitHub repository with a horizontally scaling analysis team and return only critical
          findings.
        </p>

        <div style={{ display: "grid", gap: "0.75rem", marginTop: "1rem" }}>
          <label style={{ display: "grid", gap: "0.25rem" }}>
            <span style={{ color: "var(--text-muted)" }}>Installation</span>
            <select
              className="app-search"
              value={installationId ?? ""}
              onChange={(event) => setSelectedInstallationId(event.target.value ? Number(event.target.value) : undefined)}
            >
              {activeInstallations.map((item) => (
                <option key={item.installation_id} value={item.installation_id}>
                  {item.account_login} ({item.installation_id})
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "grid", gap: "0.25rem" }}>
            <span style={{ color: "var(--text-muted)" }}>Public repository URL</span>
            <input
              className="app-search"
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              placeholder="https://github.com/owner/repo"
            />
          </label>
          {formErrors.repoUrl ? <p className="form-error-text">{formErrors.repoUrl}</p> : null}

          <label style={{ display: "grid", gap: "0.25rem" }}>
            <span style={{ color: "var(--text-muted)", display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              Branch / tag / commit (optional)
              <span
                className="info-icon"
                title="If omitted, we analyze the repository's default branch."
                aria-label="If omitted, default branch is used."
              >
                i
              </span>
            </span>
            <input
              className="app-search"
              value={targetRef}
              onChange={(event) => setTargetRef(event.target.value)}
              placeholder="main"
            />
          </label>
          {formErrors.targetRef ? <p className="form-error-text">{formErrors.targetRef}</p> : null}

          <div style={{ display: "grid", gap: "0.25rem", gridTemplateColumns: "1fr 1fr" }}>
            <label style={{ display: "grid", gap: "0.25rem" }}>
              <span style={{ color: "var(--text-muted)" }}>Token budget cap</span>
              <input
                className="app-search"
                type="number"
                value={tokenBudgetCap}
                min={10000}
                onChange={(event) => setTokenBudgetCap(Number(event.target.value))}
              />
            </label>
            {formErrors.tokenBudgetCap ? <p className="form-error-text">{formErrors.tokenBudgetCap}</p> : null}
            <label style={{ display: "grid", gap: "0.25rem" }}>
              <span style={{ color: "var(--text-muted)" }}>Cost budget cap (USD)</span>
              <input
                className="app-search"
                type="number"
                step="0.5"
                value={costBudgetCapUsd}
                min={0.5}
                onChange={(event) => setCostBudgetCapUsd(Number(event.target.value))}
              />
            </label>
            {formErrors.costBudgetCapUsd ? <p className="form-error-text">{formErrors.costBudgetCapUsd}</p> : null}
          </div>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              className="button button-ghost"
              type="button"
              disabled={!installationId || !repoUrl.trim() || estimateMutation.isPending || hasFormErrors}
              onClick={handleEstimate}
            >
              {estimateMutation.isPending ? "Estimating..." : "Estimate Cost"}
            </button>
            <button
              className="button button-primary"
              type="button"
              disabled={!installationId || !repoUrl.trim() || createMutation.isPending || !ackConfirmed || hasFormErrors}
              onClick={handleCreate}
            >
              {createMutation.isPending ? "Queuing..." : "Start Evaluation"}
            </button>
          </div>

          <label style={{ display: "flex", gap: "0.45rem", alignItems: "flex-start", color: "var(--text-muted)" }}>
            <input
              type="checkbox"
              checked={ackConfirmed}
              onChange={(event) => setAckConfirmed(event.target.checked)}
              style={{ marginTop: "0.15rem" }}
            />
            <span>
              I understand this run can be expensive for large repositories and agree to proceed under the configured
              budget cap.
            </span>
          </label>
        </div>

        {estimateMutation.data ? (
          <div
            style={{ marginTop: "1rem", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "0.75rem" }}
          >
            <p style={{ margin: 0, fontWeight: 600 }}>Cost Estimate</p>
            <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)" }}>{estimateMutation.data.warning}</p>
            <p style={{ margin: "0.5rem 0 0", color: "var(--text-muted)" }}>
              Target: {estimateMutation.data.owner}/{estimateMutation.data.repo}@{estimateMutation.data.target_ref}
            </p>
            <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)" }}>
              Files: {estimateMutation.data.file_count} · Estimated tokens: {estimateMutation.data.estimated_tokens} ·
              Estimated cost: {formatCurrency(estimateMutation.data.estimated_cost_usd)}{" "}
              <span
                className="info-icon"
                title="Estimate uses repository file count and total bytes, then converts bytes to token estimates and applies current pricing assumptions. Final cost may vary."
                aria-label="Estimate cost calculation details."
              >
                i
              </span>
            </p>
          </div>
        ) : null}
        {estimateMutation.isError ? (
          <StateBlock title="Estimate failed" description={extractApiErrorMessage(estimateMutation.error)} />
        ) : null}
        {createMutation.isError ? (
          <StateBlock title="Could not start evaluation" description={extractApiErrorMessage(createMutation.error)} />
        ) : null}
      </Panel>

      <Panel>
        <h2 style={{ marginTop: 0, marginBottom: "0.6rem" }}>Recent Code Tours</h2>
        {!installationId ? <StateBlock title="Select an installation" description="Choose an installation to load runs." /> : null}
        {installationId && evalList.isLoading ? (
          <StateBlock title="Loading tours" description="Fetching recent runs." />
        ) : null}
        {installationId && evalList.isError ? (
          <StateBlock title="Could not load tours" description={extractApiErrorMessage(evalList.error)} />
        ) : null}
        {installationId && !evalList.isLoading && !evalList.isError && (evalList.data?.length ?? 0) === 0 ? (
          <StateBlock title="No tours yet" description="Start your first repository tour above." />
        ) : null}

        {installationId && !evalList.isLoading && !evalList.isError ? (
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {evalList.data?.map((row) => {
              const isSelected = selectedEvalId === row.id;
              return (
              <article
                key={row.id}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-md)",
                  padding: "0.65rem 0.75rem",
                  display: "grid",
                  gap: "0.5rem",
                }}
              >
                <button
                  type="button"
                  className="button button-ghost"
                  style={{ justifySelf: "start" }}
                  onClick={() => setSelectedEvalId((previous) => (previous === row.id ? undefined : row.id))}
                >
                  {isSelected ? "▼" : "▶"} #{row.id} · {row.owner}/{row.repo}@{row.target_ref}
                </button>
                <span style={{ color: "var(--text-muted)" }}>
                  {row.status} · findings {row.findings_count} · cost {formatCurrency(row.cost_usd)} /{" "}
                  {formatCurrency(row.cost_budget_cap_usd)}
                </span>
                {row.status !== "complete" && row.status !== "failed" && row.status !== "canceled" ? (
                  <button
                    className="button button-danger"
                    type="button"
                    disabled={cancelMutation.isPending}
                    onClick={() => cancelMutation.mutate({ externalEvalId: row.id, installationId: row.installation_id })}
                  >
                    Cancel
                  </button>
                ) : null}
                {isSelected && installationId ? (
                  <div style={{ display: "grid", gap: "0.6rem", marginTop: "0.2rem" }}>
                    {evalDetail.isLoading ? (
                      <StateBlock title="Loading tour details" description="Fetching action chain and findings." />
                    ) : null}
                    {evalDetail.isError ? (
                      <StateBlock title="Could not load details" description={extractApiErrorMessage(evalDetail.error)} />
                    ) : null}
                    {cancelMutation.isError ? (
                      <StateBlock title="Could not cancel tour" description={extractApiErrorMessage(cancelMutation.error)} />
                    ) : null}
                    {evalDetail.data && evalDetail.data.id === row.id ? (
                      <div style={{ display: "grid", gap: "0.6rem" }}>
                        <p style={{ margin: 0, color: "var(--text-muted)" }}>
                          {evalDetail.data.summary ?? "No summary yet."}
                        </p>
                        <ExternalEvalActionChain detail={evalDetail.data} />
                        <div style={{ display: "grid", gap: "0.35rem" }}>
                          <strong>Critical findings</strong>
                          {evalDetail.data.findings.length === 0 ? (
                            <span style={{ color: "var(--text-muted)" }}>No critical findings posted yet.</span>
                          ) : (
                            evalDetail.data.findings.map((finding) => (
                              <article
                                key={finding.id}
                                style={{
                                  border: "1px solid var(--border)",
                                  borderRadius: "var(--radius-md)",
                                  padding: "0.55rem 0.65rem",
                                }}
                              >
                                <p style={{ margin: 0, fontWeight: 600 }}>
                                  [{finding.severity.toUpperCase()}] {finding.title}
                                </p>
                                <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)" }}>{finding.message}</p>
                                {finding.file_path ? (
                                  <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)" }}>
                                    {finding.file_path}
                                    {finding.line_start ? `:${finding.line_start}` : ""}
                                  </p>
                                ) : null}
                              </article>
                            ))
                          )}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </article>
              );
            })}
          </div>
        ) : null}
      </Panel>
    </section>
  );
}
