"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Remove one agent from the dashboard: a duplicate, or one that is gone. Asks in
 * place, saying exactly what happens, then calls DELETE /api/agents/{slug}.
 */
export function RemoveAgent({ slug, name }: { slug: string; name: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const remove = async () => {
    setBusy(true);
    setError("");
    const r = await fetch(`/api/agents/${encodeURIComponent(slug)}`, { method: "DELETE" }).catch(() => null);
    setBusy(false);
    if (!r?.ok) {
      setError(r?.status === 403 ? "You can't remove agents in this workspace." : "Couldn't remove it. Try again.");
      return;
    }
    router.push("/app/projects");
    router.refresh();
  };

  if (!confirming)
    return (
      <button type="button" className="k-btn-danger" onClick={() => setConfirming(true)}>
        Remove {name}…
      </button>
    );
  return (
    <div role="alertdialog" aria-label={`Remove ${name}`}>
      <p>
        <b>Remove {name}?</b> It leaves the agent list and the map, its guardrails are emptied and its tool permissions revoked. Its past traffic, issues and
        audit log are kept. If its code still exists, the next <code>agentfox init</code> proposes it again.
      </p>
      {error && (
        <p className="k-error" role="alert">
          {error}
        </p>
      )}
      <div className="k-pills">
        <button type="button" className="k-btn-danger" disabled={busy} onClick={remove}>
          {busy ? "Removing…" : "Remove"}
        </button>
        <button type="button" className="k-btn-ghost" disabled={busy} onClick={() => setConfirming(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}
