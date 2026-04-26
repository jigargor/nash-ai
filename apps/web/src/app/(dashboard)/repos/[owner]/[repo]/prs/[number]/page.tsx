import { PrReviewPageClient } from "@/components/review/pr-review-page-client";
import { StateBlock } from "@/components/ui/state-block";

interface PrDetailPageProps {
  params: Promise<{
    owner: string;
    repo: string;
    number: string;
  }>;
  searchParams: Promise<{
    reviewId?: string;
    installationId?: string;
  }>;
}

export default async function PrDetailPage({ params, searchParams }: PrDetailPageProps) {
  const { owner, repo, number } = await params;
  const sp = await searchParams;
  const reviewIdRaw = sp.reviewId;
  const installationIdRaw = sp.installationId;
  const reviewId = Number(reviewIdRaw);
  const installationId = Number(installationIdRaw);
  if (!Number.isInteger(reviewId) || reviewId <= 0 || !Number.isInteger(installationId) || installationId <= 0) {
    return (
      <StateBlock
        title={`${owner}/${repo} · PR #${number}`}
        description="Open this pull request from the dashboard review list so the matching review context can be loaded."
      />
    );
  }

  return (
    <PrReviewPageClient
      owner={owner}
      repo={repo}
      prNumber={number}
      reviewId={reviewId}
      installationId={installationId}
    />
  );
}
