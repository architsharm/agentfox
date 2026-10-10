"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

/** One click: this production path becomes a regression case that expects it. */
export function AddPathToTests({ slug, path, traceId }: { slug: string; path: string[]; traceId: string | null }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <span className="k-act">
      <button
        type="button"
        className="k-btn"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await callJson(`/api/agents/${encodeURIComponent(slug)}/tool-paths/tests`, "POST", { path, trace_id: traceId });
            router.refresh();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        Add to tests
      </button>
      {error && <span className="k-muted small">{error}</span>}
    </span>
  );
}
