"use client";

interface StreamingStatusProps {
  state: "connected" | "reconnecting" | "disconnected";
}

export function StreamingStatus({ state }: StreamingStatusProps) {
  const colorByState: Record<string, string> = {
    connected: "var(--success)",
    reconnecting: "var(--severity-medium)",
    disconnected: "var(--text-muted)",
  };
  return (
    <div className="status-pill" style={{ color: colorByState[state] }}>
      Stream: <strong style={{ marginLeft: "0.2rem" }}>{state}</strong>
    </div>
  );
}
