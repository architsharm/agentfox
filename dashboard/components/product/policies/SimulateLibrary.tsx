"use client";

import { useState } from "react";
import { Act, callJson } from "@/components/kit/Act";

type Result = { replayed: number; blocked: number; held: number; hidden: number; since_days: number };

/** "Would have blocked 3, asked a person about 1 and hidden data in 2 of 140 checks". */
export function simulationSummary(r: Result): string {
  if (!r.replayed) return `No traffic in the last ${r.since_days} days to replay. Blocking is allowed now; nothing tells you yet what it will stop.`;
  const parts = [`blocked ${r.blocked}`, r.held ? `asked a person about ${r.held}` : "", r.hidden ? `hidden data in ${r.hidden}` : ""].filter(Boolean);
  const last = parts.length > 1 ? ` and ${parts.pop()}` : "";
  return `Last ${r.since_days} days: would have ${parts.join(", ")}${last} of ${r.replayed} checks.`;
}

/**
 * Replay the project's recent traffic against its copies of a library, as if they
 * blocked, and say what they would have done. The simulation is recorded: it is what
 * lets "Start blocking" through.
 */
export function SimulateLibrary({ library, body, onSimulated }: { library: string; body: unknown; onSimulated?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
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
            setNote(simulationSummary(await callJson(`/api/policies/libraries/${library}/simulate`, "POST", body)));
            onSimulated?.();
          } catch (e: any) {
            setError(e.message || "Failed");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "…" : "Simulate"}
      </button>
      {note && (
        <span className="k-act-note" role="status">
          {note}
        </span>
      )}
      {error && (
        <span className="k-act-error" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}

/**
 * Simulate, then Start blocking. A successful simulation resets the Start blocking
 * button, so a "simulate first" refusal from before it doesn't stay on screen.
 */
export function SimulateThenBlock({ library, body, confirm }: { library: string; body: object; confirm: string }) {
  const [round, setRound] = useState(0);
  return (
    <>
      <SimulateLibrary library={library} body={body} onSimulated={() => setRound((r) => r + 1)} />
      <Act key={round} url={`/api/policies/libraries/${library}/mode`} body={{ ...body, mode: "enforce" }} className="k-btn" done="Blocking" confirm={confirm}>
        Start blocking
      </Act>
    </>
  );
}
