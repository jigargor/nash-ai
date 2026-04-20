"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { shouldInvalidateReviewQueries } from "@/lib/review-stream-invalidation";

export interface ReviewStreamEvent {
  type: string;
  status?: string;
  message?: string;
}

export function useReviewStream(reviewId: number) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<ReviewStreamEvent[]>([]);
  const [connectionState, setConnectionState] = useState<"connected" | "reconnecting" | "disconnected">(
    "disconnected",
  );

  useEffect(() => {
    if (!reviewId) return undefined;

    const eventSource = new EventSource(`/api/v1/reviews/${reviewId}/stream`);
    setConnectionState("connected");

    eventSource.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as ReviewStreamEvent;
        setEvents((previous) => [...previous, parsed]);
        if (shouldInvalidateReviewQueries(parsed)) {
          void queryClient.invalidateQueries({ queryKey: ["review", reviewId] });
          void queryClient.invalidateQueries({ queryKey: ["reviews"] });
        }
        if (parsed.type === "complete") eventSource.close();
      } catch {
        setEvents((previous) => [...previous, { type: "error", message: "Invalid stream event payload" }]);
      }
    };

    eventSource.onerror = () => {
      setConnectionState("reconnecting");
    };

    return () => {
      setConnectionState("disconnected");
      eventSource.close();
    };
  }, [queryClient, reviewId]);

  return { events, connectionState };
}
