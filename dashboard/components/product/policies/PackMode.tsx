"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Act, callJson } from "@/components/kit/Act";
import { packWouldStop } from "@/lib/product/libraries";

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
  secondary = false,
}: {
  packKey: string;
  mode: string | null;
  body: string;
  version: number | null;
  /** Requests the pack's watching rules flagged in the window. */
  wouldStop?: number;
  /** Not the card's main action: a plain button (Libraries keeps one primary per card). */
  secondary?: boolean;
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
    // Asked in the page, as every other switch is: a native dialog can be suppressed.
    return (
      <Act url={`/api/policies/${encodeURIComponent(packKey)}/mode`} body={{ mode: "observe" }} className="k-btn" done="Watching" confirm="Back to watching? Its rules will record what they would do, and stop nothing.">
        Back to watching
      </Act>
    );
  }

  return (
    <span className="k-act" style={{ flexWrap: "wrap" }}>
      {!sim ? (
        <button
          className={secondary ? "k-btn" : "k-btn-primary"}
          disabled={busy}
          onClick={() =>
            run(async () => {
              setSim(await callJson(`/api/policies/simulate-persist`, "POST", { body }));
            })
          }
        >
          {busy ? "Checking…" : "Simulate"}
        </button>
      ) : (
        <span className="k-preview k-preview-inline">
          <span>
            Last 7 days: <strong>{wouldStop ?? packWouldStop(sim)}</strong> would have been stopped
            {sim?.counts?.already_stopped ? `; it also catches ${sim.counts.already_stopped} that other rules already stopped` : ""}
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
            Start blocking
          </button>
          <button className="k-btn-ghost" onClick={() => setSim(null)}>
            Cancel
          </button>
        </span>
      )}
      {error && <span className="k-act-error" role="alert">{error}</span>}
    </span>
  );
}
