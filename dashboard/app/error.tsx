"use client";

/**
 * The last line of defence: a render or fetch threw somewhere no page caught it.
 *
 * Next replaces the page body with this and keeps the shell (sidebar, topbar)
 * around it, so the reader keeps their bearings instead of losing the whole app
 * to a blank screen. Two jobs only — say in plain words what failed, and offer
 * the one action that can recover it (`reset()` re-renders the segment, which
 * retries every fetch the page made).
 */

import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // "/" is the public landing page, so a failure inside the app goes back to the
  // app's own Overview and a failure on a public page goes home.
  const inApp = (usePathname() ?? "").startsWith("/app");
  useEffect(() => {
    // Server-side digests are all a reader gets in production; logging the real
    // error client-side is what makes a bug report reproducible.
    console.error("Page failed to render:", error);
  }, [error]);

  return (
    <>
      <h1>This page did not load</h1>
      <div className="hero">
        <div className="hero-title">Something failed while building this page</div>
        <p>
          The rest of the app is still working, so this is not a sign-out and not
          data loss. It is usually a request to the control plane that failed part
          way through, and trying again often works.
        </p>
        <p className="small muted">
          If it keeps failing, the detail below is what a bug report needs.
        </p>
        <div className="row" style={{ marginTop: 14 }}>
          <button type="button" className="btn-primary" onClick={() => reset()}>
            Try again
          </button>
          <Link href={inApp ? "/app" : "/"} className="cta" style={{ marginTop: 0 }}>
            {inApp ? "Back to Overview" : "Back to home"}
          </Link>
        </div>
        {(error?.message || error?.digest) && (
          <p className="small mono muted" style={{ marginTop: 16, wordBreak: "break-word" }}>
            {error.message || `error ${error.digest}`}
          </p>
        )}
      </div>
    </>
  );
}
