import { PrReviewPageClient } from "@/components/review/pr-review-page-client";

interface PrDetailPageProps {
  params: Promise<{
    owner: string;
    repo: string;
    number: string;
  }>;
  searchParams: Promise<{
    reviewId?: string;
  }>;
}

export default async function PrDetailPage({ params, searchParams }: PrDetailPageProps) {
  const { owner, repo, number } = await params;
  const sp = await searchParams;
  const reviewIdRaw = sp.reviewId;
  const reviewId = Number(reviewIdRaw);
  // #region agent log
  fetch("http://127.0.0.1:7582/ingest/e6a057ab-47e4-4505-9884-d384fd412c69",{method:"POST",headers:{"Content-Type":"application/json","X-Debug-Session-Id":"7b2718"},body:JSON.stringify({sessionId:"7b2718",runId:"pre-fix-1",hypothesisId:"H3",location:"app/(dashboard)/repos/[owner]/[repo]/prs/[number]/page.tsx:21",message:"pr_detail_page_inputs",data:{owner,repo,number,reviewIdRaw,reviewIdParsed:reviewId,isValidReviewId:Number.isInteger(reviewId)&&reviewId>0},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
  if (!Number.isInteger(reviewId) || reviewId <= 0) {
    throw new Error("Missing or invalid reviewId query parameter.");
  }

  return <PrReviewPageClient owner={owner} repo={repo} prNumber={number} reviewId={reviewId} />;
}
