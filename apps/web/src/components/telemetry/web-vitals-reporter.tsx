"use client";

import { useReportWebVitals } from "next/web-vitals";

function shouldLogVitals(): boolean {
  return process.env.NODE_ENV !== "production" || process.env.NEXT_PUBLIC_WEB_VITALS_DEBUG === "1";
}

export function WebVitalsReporter() {
  useReportWebVitals((metric) => {
    if (!shouldLogVitals()) return;
    console.debug("[web-vitals]", metric.name, metric.value, metric.rating);
  });

  return null;
}
