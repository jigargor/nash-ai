"use client";

import type { ReviewStreamEvent } from "@/hooks/use-review-stream";

interface ReviewTimelineProps {
  events: ReviewStreamEvent[];
}

export function ReviewTimeline({ events }: ReviewTimelineProps) {
  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: "0.75rem",
        background: "var(--card)",
        padding: "0.75rem",
      }}
    >
      <h3 style={{ marginTop: 0 }}>Agent timeline</h3>
      {events.length === 0 ? <p style={{ color: "var(--text-muted)" }}>Waiting for stream events...</p> : null}
      {events.map((event, index) => (
        <div key={`${event.type}-${index}`} style={{ fontFamily: "var(--font-geist-mono)", fontSize: "0.85rem" }}>
          {event.type}
          {event.status ? ` · ${event.status}` : ""}
          {event.message ? ` · ${event.message}` : ""}
        </div>
      ))}
    </section>
  );
}
