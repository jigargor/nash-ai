"use client";

import { useEffect, useState } from "react";

import type { ReviewStreamEvent } from "@/hooks/use-review-stream";
import { Panel } from "@/components/ui/panel";

interface ReviewTimelineProps {
  events: ReviewStreamEvent[];
  reviewStartedAt?: string | null;
  reviewCompletedAt?: string | null;
  isInFlight: boolean;
}

function formatReviewInstantDetailed(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

function formatElapsedMs(ms: number): string {
  if (ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  if (hours > 0)
    return `${hours} h ${minutes % 60} m ${seconds % 60} s`;
  if (minutes > 0) return `${minutes} m ${seconds % 60} s`;
  return `${seconds} s`;
}

export function ReviewTimeline({
  events,
  reviewStartedAt,
  reviewCompletedAt,
  isInFlight,
}: ReviewTimelineProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const startMs = reviewStartedAt ? Date.parse(reviewStartedAt) : NaN;
  const endMs = reviewCompletedAt ? Date.parse(reviewCompletedAt) : NaN;

  useEffect(() => {
    if (!isInFlight || !Number.isFinite(startMs)) return;
    const interval = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [isInFlight, startMs]);

  let runtimeMs: number | null = null;
  if (Number.isFinite(startMs) && Number.isFinite(endMs)) runtimeMs = endMs - startMs;
  else if (Number.isFinite(startMs)) {
    runtimeMs = isInFlight ? nowMs - startMs : null;
  }

  return (
    <Panel>
      <h3 style={{ marginTop: 0 }}>Agent timeline</h3>
      <div
        style={{
          display: "grid",
          gap: "0.35rem",
          fontSize: "0.82rem",
          color: "var(--text-muted)",
          marginBottom: events.length > 0 ? "0.75rem" : 0,
          paddingBottom: events.length > 0 ? "0.65rem" : 0,
          borderBottom: events.length > 0 ? "1px solid var(--border)" : "none",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap" }}>
          <span>Started</span>
          <span style={{ color: "var(--text-primary)", fontFamily: "var(--font-geist-mono), ui-monospace, monospace" }}>
            {formatReviewInstantDetailed(reviewStartedAt ?? undefined)}
          </span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap" }}>
          <span>Ended</span>
          <span style={{ color: "var(--text-primary)", fontFamily: "var(--font-geist-mono), ui-monospace, monospace" }}>
            {isInFlight && !reviewCompletedAt ? "Still running…" : formatReviewInstantDetailed(reviewCompletedAt)}
          </span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap" }}>
          <span>Total runtime</span>
          <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
            {runtimeMs !== null ? formatElapsedMs(runtimeMs) : "—"}
            {runtimeMs !== null && isInFlight ? " so far" : ""}
          </span>
        </div>
      </div>
      {events.length === 0 ? <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>Waiting for stream events…</p> : null}
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
