"use client";

import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    turnstile?: {
      remove: (widgetId: string) => void;
      render: (
        container: HTMLElement,
        options: {
          callback: (token: string) => void;
          "error-callback"?: (errorCode?: string | number) => void;
          "expired-callback"?: () => void;
          "timeout-callback"?: () => void;
          "unsupported-callback"?: () => void;
          "refresh-expired"?: "auto" | "manual" | "never";
          "refresh-timeout"?: "auto" | "manual" | "never";
          retry?: "auto" | "never";
          size?: "normal" | "flexible" | "compact";
          sitekey: string;
          theme?: "light" | "dark" | "auto";
        },
      ) => string;
    };
  }
}

const TURNSTILE_SCRIPT_ID = "cf-turnstile-script";
const TURNSTILE_SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface TurnstileWidgetProps {
  onError?: (errorCode?: string | number) => void;
  onExpired?: () => void;
  onToken: (token: string) => void;
  onTimeout?: () => void;
  onUnsupported?: () => void;
  siteKey: string;
}

export function TurnstileWidget({ onError, onExpired, onTimeout, onToken, onUnsupported, siteKey }: TurnstileWidgetProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [isScriptReady, setIsScriptReady] = useState(() => typeof window !== "undefined" && Boolean(window.turnstile));

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.turnstile) {
      queueMicrotask(() => setIsScriptReady(true));
      return;
    }

    const existing = document.getElementById(TURNSTILE_SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      const handleLoad = () => setIsScriptReady(true);
      const handleError = () => onError?.();
      existing.addEventListener("load", handleLoad);
      existing.addEventListener("error", handleError);
      return () => {
        existing.removeEventListener("load", handleLoad);
        existing.removeEventListener("error", handleError);
      };
    }

    const script = document.createElement("script");
    script.id = TURNSTILE_SCRIPT_ID;
    script.src = TURNSTILE_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => setIsScriptReady(true);
    script.onerror = () => onError?.();
    document.head.appendChild(script);
  }, [onError]);

  useEffect(() => {
    if (!isScriptReady || !containerRef.current || !window.turnstile) return;
    widgetIdRef.current = window.turnstile.render(containerRef.current, {
      sitekey: siteKey,
      callback: onToken,
      "error-callback": onError,
      "expired-callback": onExpired,
      "refresh-expired": "auto",
      "refresh-timeout": "auto",
      "timeout-callback": onTimeout,
      "unsupported-callback": onUnsupported,
      retry: "auto",
      size: "flexible",
      theme: "dark",
    });

    return () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, [isScriptReady, onError, onExpired, onTimeout, onToken, onUnsupported, siteKey]);

  return (
    <div style={{ minHeight: "72px" }}>
      <div ref={containerRef} />
    </div>
  );
}

