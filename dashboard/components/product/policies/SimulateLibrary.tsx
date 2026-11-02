"use client";

import { useState } from "react";
import { Act, callJson } from "@/components/kit/Act";
import { simulationSummary } from "@/lib/product/libraries";

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
