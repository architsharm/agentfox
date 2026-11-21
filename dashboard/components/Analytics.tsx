"use client";

import Script from "next/script";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { reported, SIGNUP_KEY } from "@/lib/analytics";

declare global {
  interface Window {
    umami?: { track: (name?: string, data?: Record<string, string>) => void };
  }
}

/**
 * Umami, cookie-less page counting, served only when the deployment sets
 * AGENTFOX_UMAMI_WEBSITE_ID (the hosted site does; a self-hosted copy does not and
 * so reports nothing to us). Auto-tracking is off and page views are sent by hand
 * so lib/analytics.ts decides which URLs leave the browser.
 */
export function Analytics({ websiteId }: { websiteId?: string }) {
  const pathname = usePathname();
  const loaded = useRef(false);
  useEffect(() => {
    if (loaded.current) view(pathname);
  }, [pathname]);
  if (!websiteId) return null;
  return (
    <Script
      src="https://cloud.umami.is/script.js"
      data-website-id={websiteId}
      data-auto-track="false"
      strategy="afterInteractive"
      onLoad={() => {
        loaded.current = true;
        view(pathname);
      }}
    />
  );
}

function view(pathname: string) {
  if (!reported(pathname)) return;
  window.umami?.track();
  // shortcut: one browser counts one sign-up whatever the account, upgrade to a server-side event if that ever matters.
  if (pathname === "/app/welcome") {
    try {
      if (!localStorage.getItem(SIGNUP_KEY)) {
        localStorage.setItem(SIGNUP_KEY, "1");
        window.umami?.track("signup");
      }
    } catch {}
  }
}
