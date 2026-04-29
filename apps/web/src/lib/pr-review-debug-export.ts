import type { Finding, FindingOutcome } from "@ai-code-review/shared-types";

import type { ReviewModelAudit } from "@/lib/api/reviews";

export interface PrReviewDebugExportInput {
  exportedAtIso: string;
  reviewId: number;
  owner: string;
  repo: string;
  prNumber: string;
  status: string;
  summaryParagraph: string;
  model: string | undefined;
  modelProvider: string | undefined;
  tokensUsed: number | null | undefined;
  costUsd: string | null | undefined;
  postedFindingsCount: number;
  pipelineStagedFindingsPeak: number;
  postedFindings: Finding[];
  findingOutcomes: FindingOutcome[];
  modelAudits: ReviewModelAudit[];
  debugArtifacts: Record<string, unknown> | null;
}

/** Serializable bundle for support / debugging: pipeline audits, artifacts, posted findings, outcomes. */
export function buildPrReviewDebugExport(input: PrReviewDebugExportInput): Record<string, unknown> {
  return {
    exported_at: input.exportedAtIso,
    review: {
      id: input.reviewId,
      status: input.status,
      repo: `${input.owner}/${input.repo}`,
      pr_number: input.prNumber,
      summary: input.summaryParagraph,
      model: input.model ?? null,
      model_provider: input.modelProvider ?? null,
      tokens_used: input.tokensUsed ?? null,
      cost_usd: input.costUsd ?? null,
      posted_findings_count: input.postedFindingsCount,
      pipeline_staged_findings_peak: input.pipelineStagedFindingsPeak,
    },
    action_chain: { stages: input.modelAudits },
    debug_artifacts: input.debugArtifacts,
    posted_findings: input.postedFindings,
    finding_outcomes: input.findingOutcomes,
    diff_and_inline_comments: {
      note:
        "Raw unified diff is not attached here; posted_findings and finding_outcomes mirror what was (or would be) posted as inline review comments.",
    },
  };
}
