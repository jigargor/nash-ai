const TERMINAL_EXTERNAL_EVAL_STATUSES: ReadonlySet<string> = new Set(["complete", "failed", "partial", "canceled"]);

/** External evaluation statuses after which no further server-side progress is expected. */
export function isExternalEvalTerminalStatus(status: string | undefined | null): boolean {
  return Boolean(status) && TERMINAL_EXTERNAL_EVAL_STATUSES.has(status as string);
}

/** True while any row may still change; polling stops once every row is terminal (or the list is empty). */
export function hasNonTerminalExternalEval(items: ReadonlyArray<{ status: string }> | undefined): boolean {
  return Boolean(items?.some((item) => !isExternalEvalTerminalStatus(item.status)));
}
