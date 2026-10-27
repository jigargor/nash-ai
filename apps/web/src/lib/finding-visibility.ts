import type { Finding } from "@ai-code-review/shared-types";

/** Reads `debug_artifacts.dismissed_findings` (indices into the review's findings array). */
export function getDismissedFindingIndices(
  debugArtifacts: Record<string, unknown> | null | undefined,
): ReadonlySet<number> {
  const raw = debugArtifacts?.dismissed_findings;
  if (!Array.isArray(raw)) return new Set();
  return new Set(raw.filter((value): value is number => Number.isInteger(value) && (value as number) >= 0));
}

/** A finding is visible unless dismissed and the "show dismissed" toggle is off. */
export function isFindingVisible(
  _finding: Finding,
  index: number,
  dismissedIndices: ReadonlySet<number>,
  showDismissed: boolean,
): boolean {
  return showDismissed || !dismissedIndices.has(index);
}

export interface IndexedFinding {
  finding: Finding;
  /** Index in the review's original findings array (what the dismiss API expects). */
  originalIndex: number;
}

export function filterVisibleFindings(
  findings: readonly Finding[],
  dismissedIndices: ReadonlySet<number>,
  showDismissed: boolean,
): IndexedFinding[] {
  const visible: IndexedFinding[] = [];
  findings.forEach((finding, originalIndex) => {
    if (isFindingVisible(finding, originalIndex, dismissedIndices, showDismissed))
      visible.push({ finding, originalIndex });
  });
  return visible;
}
