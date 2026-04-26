import { PrReviewPageClient } from "@/components/review/pr-review-page-client";

interface PrDetailPageProps {
  params: {
    owner: string;
    repo: string;
    number: string;
  };
  searchParams: {
    reviewId?: string;
  };
}

export default function PrDetailPage({ params, searchParams }: PrDetailPageProps) {
  const reviewId = Number(searchParams.reviewId);
  if (!Number.isInteger(reviewId) || reviewId <= 0) {
    throw new Error("Missing or invalid reviewId query parameter.");
  }

  return <PrReviewPageClient owner={params.owner} repo={params.repo} prNumber={params.number} reviewId={reviewId} />;
}
