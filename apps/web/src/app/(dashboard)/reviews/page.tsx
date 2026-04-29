import { Suspense } from "react";

import { StateBlock } from "@/components/ui/state-block";
import { ReviewsPageClient } from "./reviews-page-client";

export const dynamic = "force-dynamic";

export default function ReviewsPage() {
  return (
    <Suspense fallback={<StateBlock title="Loading reviews" description="Preparing review filters." />}>
      <ReviewsPageClient />
    </Suspense>
  );
}
