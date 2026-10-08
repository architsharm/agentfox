"use client";

import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

/**
 * A button that calls one of this app's JSON routes and refreshes the page.
 * Errors show inline next to the button; nothing navigates away.
 */
export async function callJson(url: string, method: string, body?: unknown): Promise<any> {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || res.statusText);
    throw new Error(detail);
  }
  return data;
}

export function Act({
  url,
  method = "POST",
  body,
  children,
  className = "k-btn",
  confirm,
  done,
}: {
  url: string;
  method?: string;
  body?: unknown;
  children: ReactNode;
  className?: string;
  confirm?: string;
  /** Label shown briefly after success. */
  done?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState(false);
  return (
    <span className="k-act">
      <button
        type="button"
        className={className}
        disabled={busy}
        onClick={async () => {
          if (confirm && !window.confirm(confirm)) return;
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
        }}
      >
        {busy ? "…" : ok && done ? done : children}
      </button>
      {error && (
        <span className="k-act-error" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
