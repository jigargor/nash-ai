/** Review worker / queue states that should trigger UI polling and in-progress affordances. */
export function isReviewInFlightStatus(status: string | undefined | null): boolean {
  if (!status) return false;
  return status === "queued" || status === "running";
}
