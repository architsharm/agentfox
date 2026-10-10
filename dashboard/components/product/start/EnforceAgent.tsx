"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

type Preview = { packs: { key: string; label: string; would_stop: number }[]; would_stop: number };

/**
 * Get started, step 6: everything that protects this agent goes from watching to
 * enforcing in one go (baseline checks, its own protections, blocked words and
 * topics), after showing what each would have stopped last week.
 */
export function EnforceAgent({ agent }: { agent: string }) {
  const router = useRouter();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string[] | null>(null);
  const [error, setError] = useState("");
  const base = `/api/agents/${encodeURIComponent(agent)}/enforcement`;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e: any) {
      setError(e.message || "Failed");
    } finally {
      setBusy(false);
    }
  };

  if (done)
    return (
      <div className="note-panel">
        Enforcing now: {done.length ? done.join(", ") : "everything was already enforcing"}. Requests that break a rule are stopped from
        here on.
      </div>
    );

  if (!preview)
    return (
      <div className="gs-row">
        <button className="k-btn-primary" disabled={busy} onClick={() => run(async () => setPreview(await callJson(`${base}/preview`, "POST", {})))}>
          {busy ? "Checking the last 7 days…" : "Review and turn on"}
        </button>
        {error && <span className="k-act-error">{error}</span>}
      </div>
    );

  return (
    <div className="k-preview" style={{ maxWidth: "none" }}>
      {preview.packs.length ? (
        <>
          <div className="k-preview-head">
            <strong>
              {preview.would_stop} request{preview.would_stop === 1 ? "" : "s"} in the last 7 days would have been stopped or held
            </strong>
          </div>
          <ul className="k-plain" style={{ margin: "8px 0" }}>
            {preview.packs.map((p) => (
              <li key={p.key}>
                {p.label}
                <span className="k-muted"> · {p.would_stop} would have been stopped</span>
              </li>
            ))}
          </ul>
          <div className="gs-row">
            <button
              className="k-btn-primary"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const out = await callJson(base, "POST", {});
                  setDone((out.enforcing || []).map((p: any) => p.label));
                  router.refresh();
                })
              }
            >
              {busy ? "Turning on…" : "Turn on enforcement"}
            </button>
            <button className="k-btn-ghost" disabled={busy} onClick={() => setPreview(null)}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <div>Everything that protects this agent is already enforcing.</div>
      )}
      {error && <div className="k-act-error">{error}</div>}
    </div>
  );
}
