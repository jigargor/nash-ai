"use client";

import type { ReviewStreamEvent } from "@/hooks/use-review-stream";
import { Panel } from "@/components/ui/panel";

interface ReviewTimelineProps {
  events: ReviewStreamEvent[];
}

export function ReviewTimeline({ events }: ReviewTimelineProps) {
  return (
    <Panel>
      <h3 style={{ marginTop: 0 }}>Agent timeline</h3>
      {events.length === 0 ? <p style={{ color: "var(--text-muted)" }}>Waiting for stream events...</p> : null}
      {events.map((event, index) => (
        <div key={`${event.type}-${index}`} style={{ fontFamily: "var(--font-geist-mono)", fontSize: "0.85rem" }}>
          {event.type}
          {event.status ? ` · ${event.status}` : ""}
          {event.message ? ` · ${event.message}` : ""}
        </div>
      ))}
    </Panel>
  );
}
