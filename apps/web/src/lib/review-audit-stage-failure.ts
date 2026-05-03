/**
 * Heuristic for whether audit `metadata.reason` should mark a pipeline stage as failed in UI.
 * Avoids matching the substring "error" because successful rationales often mention
 * "error handling" or similar without any provider failure.
 */
export function doesAuditReasonTextSuggestStageFailure(reason: string | undefined): boolean {
  if (reason == null || reason.length === 0) return false;
  return reason.toLowerCase().includes("failed");
}
