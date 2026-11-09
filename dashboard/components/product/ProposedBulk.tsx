"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * "Add all" and "Dismiss all" for a group of proposed agents (one repository, or the
 * whole filtered list). Dismiss asks in place first: it is many rows at once.
 * `project`: the repository the agents came from, added with its own route; without
 * one, Add all is not offered (each is added on its row).
 */
export function ProposedBulk({ ids, project, label }: { ids: string[]; project?: string | null; label: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const n = ids.length;

  const run = async (url: string, body?: unknown) => {
    setBusy(true);
    setError("");
    const r = await fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    setBusy(false);
    setConfirming(false);
    if (!r?.ok) {
      setError(r?.status === 403 ? "You can't change agents in this workspace." : "Couldn't do that. Try again.");
      return;
    }
    router.refresh();
  };

  return (
    <span className="k-pills">
      {error && (
        <span className="k-error" role="alert">
          {error}
        </span>
      )}
      {confirming ? (
        <span className="k-pills" role="alertdialog" aria-label={`Dismiss ${label}`}>
          <span className="muted">
            Dismiss {n === 1 ? "this agent" : `these ${n}`}? {n === 1 ? "It" : "They"} leave Proposed; the next scan or init proposes {n === 1 ? "it" : "them"} again.
          </span>
          <button type="button" className="k-btn-danger" disabled={busy} onClick={() => run("/api/agents/reject", { ids })}>
            Dismiss {n}
          </button>
          <button type="button" className="k-btn-ghost" disabled={busy} onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </span>
      ) : (
        <button type="button" className="k-btn-ghost" disabled={busy || !n} onClick={() => setConfirming(true)}>
          Dismiss all {n}
        </button>
      )}
      {project && !confirming && (
        <button type="button" className="k-btn-primary" disabled={busy || !n} onClick={() => run(`/api/projects/${encodeURIComponent(project)}/approve`)}>
          {busy ? "Adding…" : `Add all ${n}`}
        </button>
      )}
    </span>
  );
}
