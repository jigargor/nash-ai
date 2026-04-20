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
  const fallbackReviewId = Number(params.number) || 1;
  const reviewId = Number(searchParams.reviewId ?? fallbackReviewId);

  return <PrReviewPageClient owner={params.owner} repo={params.repo} prNumber={params.number} reviewId={reviewId} />;
}
