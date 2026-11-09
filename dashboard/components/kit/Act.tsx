"use client";

import { useRouter } from "next/navigation";
import { detailText } from "@/lib/product/errors";
import { useState, type ReactNode } from "react";

/**
 * A button that calls one of this app's JSON routes and refreshes the page.
 * Errors show inline next to the button; nothing navigates away.
 */
export async function callJson(url: string, method: string, body?: unknown): Promise<any> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // The browser's own words ("Failed to fetch", "Load failed") say nothing useful.
    throw new Error(NETWORK_ERROR);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // statusText is empty over HTTP/2, which left forms showing an empty error.
    throw new Error(detailText(data.detail) || res.statusText || `Request failed (${res.status}). Try again.`);
  }
  return data;
}

export const NETWORK_ERROR = "Could not reach the server. Check your connection and try again.";

export function Act({
  url,
  method = "POST",
  body,
  children,
  className = "k-btn",
  confirm,
  done,
  disabled = false,
  title,
}: {
  url: string;
  method?: string;
  body?: unknown;
  children: ReactNode;
  className?: string;
  confirm?: string;
  /** Label shown briefly after success. */
  done?: string;
  /** Not available yet (say why in ``title``). */
  disabled?: boolean;
  title?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState(false);
  // Asked in the page, not with window.confirm: some browsers (the in-app one among
  // them) suppress native dialogs, and the button then silently did nothing.
  const [asking, setAsking] = useState(false);
  const run = async () => {
    setAsking(false);
    setBusy(true);
    setError("");
    try {
      await callJson(url, method, body);
      setOk(true);
      setTimeout(() => setOk(false), 1500);
      router.refresh();
    } catch (e: any) {
      setError(e.message || "Failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="k-act">
      {asking ? (
        <span className="k-act-confirm" role="alertdialog" aria-label={confirm}>
          <span>{confirm}</span>
          <button type="button" className={className} onClick={run}>
            {children}
          </button>
          <button type="button" className="k-btn-ghost" onClick={() => setAsking(false)}>
            Cancel
          </button>
        </span>
      ) : (
        <button type="button" className={className} disabled={busy || disabled} title={title} onClick={() => (confirm ? (setError(""), setAsking(true)) : run())}>
          {busy ? "…" : ok && done ? done : children}
        </button>
      )}
      {error && (
        <span className="k-act-error" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
