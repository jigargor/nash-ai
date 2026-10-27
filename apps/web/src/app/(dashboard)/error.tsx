"use client";

import { Button } from "@/components/ui/button";
import { StateBlock } from "@/components/ui/state-block";

interface DashboardErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function DashboardError({ error, reset }: DashboardErrorProps) {
  return (
    <StateBlock
      title="Something went wrong"
      description={
        error.digest
          ? `The dashboard hit an unexpected error (ref ${error.digest}). Try again.`
          : "The dashboard hit an unexpected error. Try again."
      }
      action={<Button onClick={reset}>Try again</Button>}
    />
  );
}
