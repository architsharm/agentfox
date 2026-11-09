"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Act, callJson } from "@/components/kit/Act";
import { businessWouldStop } from "@/lib/product/libraries";

/**
 * Watching ↔ blocking for one business rule (an approval limit), through the same
 * gate as a library or pack: Start blocking first replays the last 7 days of calls
 * through the rule and says what it would have held, then a second Start blocking
 * confirms. The gateway refuses to enforce without that recorded simulation.
 * Going back to watching asks first, as a pack's does.
 */
export function BusinessMode({ ruleKey, mode, name }: { ruleKey: string; mode: string | null; name: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sim, setSim] = useState<any>(null);
  const base = `/api/business/rules/${encodeURIComponent(ruleKey)}`;

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

  if (mode === "enforce")
    return (
      <Act url={`${base}/mode`} body={{ mode: "observe" }} className="k-btn" done="Watching" confirm={`Put ${name} back to watching? It will record the calls it would hold, and hold nothing.`}>
        Back to watching
      </Act>
    );

  return (
    <span className="k-act" style={{ flexWrap: "wrap" }}>
      {!sim ? (
        <button className="k-btn-primary" disabled={busy} onClick={() => run(async () => setSim(await callJson(`${base}/simulate`, "POST", {})))}>
          {busy ? "Checking…" : "Start blocking"}
        </button>
      ) : (
        <span className="k-preview k-preview-inline">
          <span>
            Last {sim.since_days ?? 7} days: <strong>{businessWouldStop(sim)}</strong> would have been held
            {sim.replayed ? ` of ${sim.replayed} calls` : " (no calls to replay yet)"}
            {sim.counts?.already_stopped ? `; it also catches ${sim.counts.already_stopped} that something else already stopped` : ""}
          </span>
          <button
            className="k-btn-primary"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await callJson(`${base}/mode`, "POST", { mode: "enforce" });
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
