"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

/**
 * Watching ↔ enforcing for a whole pack. Enforcing first replays the pack over the
 * last 7 days and shows what it would have stopped; the gateway refuses to enforce
 * without that recorded simulation, and so does this button.
 */
export function PackMode({
  packKey,
  mode,
  body,
  version,
  wouldStop,
}: {
  packKey: string;
  mode: string | null;
  body: string;
  version: number | null;
  /** Requests the pack's watching rules flagged in the window. */
  wouldStop?: number;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sim, setSim] = useState<any>(null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (mode === "enforce") {
    return (
      <span className="k-act">
        <button
          className="k-btn"
          disabled={busy}
          onClick={() =>
            window.confirm("Switch to watching? Its rules will record what they would do, and stop nothing.") &&
            run(async () => {
              await callJson(`/api/policies/${encodeURIComponent(packKey)}/mode`, "POST", { mode: "observe" });
              router.refresh();
            })
          }
        >
          Switch to watching
        </button>
        {error && <span className="k-act-error">{error}</span>}
      </span>
    );
  }

  return (
    <span className="k-act" style={{ flexWrap: "wrap" }}>
      {!sim ? (
        <button
          className="k-btn-primary"
          disabled={busy}
          onClick={() =>
            run(async () => {
              setSim(await callJson(`/api/policies/simulate-persist`, "POST", { body }));
            })
          }
        >
          {busy ? "Checking…" : "Start enforcing"}
        </button>
      ) : (
        <span className="k-preview k-preview-inline">
          <span>
            Last 7 days: <strong>{wouldStop ?? sim.counts?.newly_blocked ?? 0}</strong> would have been stopped
          </span>
          <button
            className="k-btn-primary"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await callJson(`/api/policies/${encodeURIComponent(packKey)}/mode`, "POST", { mode: "enforce", ...(version ? { version } : {}) });
                setSim(null);
                router.refresh();
              })
            }
          >
            Enforce
          </button>
          <button className="k-btn-ghost" onClick={() => setSim(null)}>
            Cancel
          </button>
        </span>
      )}
      {error && <span className="k-act-error">{error}</span>}
    </span>
  );
}
