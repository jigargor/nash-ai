interface ReviewStreamEvent {
  type: string;
  status?: string;
}

export function shouldInvalidateReviewQueries(event: ReviewStreamEvent): boolean {
  return ["complete", "status"].includes(event.type) || ["done", "failed"].includes(event.status ?? "");
}
