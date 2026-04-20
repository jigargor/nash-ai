"use client";

interface StreamingStatusProps {
  state: "connected" | "reconnecting" | "disconnected";
}

export function StreamingStatus({ state }: StreamingStatusProps) {
  const colorByState: Record<string, string> = {
    connected: "var(--severity-low)",
    reconnecting: "var(--severity-medium)",
    disconnected: "var(--text-muted)",
  };
  return (
    <div style={{ color: colorByState[state], fontSize: "0.85rem" }}>
      Stream: <strong>{state}</strong>
    </div>
  );
}
