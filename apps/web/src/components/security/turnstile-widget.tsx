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
          "error-callback"?: () => void;
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
  onError?: () => void;
  onToken: (token: string) => void;
  siteKey: string;
}

export function TurnstileWidget({ onError, onToken, siteKey }: TurnstileWidgetProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [isScriptReady, setIsScriptReady] = useState(() => typeof window !== "undefined" && Boolean(window.turnstile));

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.turnstile) {
      setIsScriptReady(true);
      return;
    }

    const existing = document.getElementById(TURNSTILE_SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      const handleLoad = () => setIsScriptReady(true);
      existing.addEventListener("load", handleLoad);
      return () => existing.removeEventListener("load", handleLoad);
    }

    const script = document.createElement("script");
    script.id = TURNSTILE_SCRIPT_ID;
    script.src = TURNSTILE_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => setIsScriptReady(true);
    document.head.appendChild(script);
  }, []);

  useEffect(() => {
    if (!isScriptReady || !containerRef.current || !window.turnstile) return;
    widgetIdRef.current = window.turnstile.render(containerRef.current, {
      sitekey: siteKey,
      callback: onToken,
      "error-callback": () => onError?.(),
      theme: "auto",
    });

    return () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, [isScriptReady, onError, onToken, siteKey]);

  return <div ref={containerRef} />;
}

