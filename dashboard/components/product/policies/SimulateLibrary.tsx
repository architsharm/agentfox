"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Act, callJson } from "@/components/kit/Act";
import { simulationSummary } from "@/lib/product/libraries";

/**
 * Replay the project's recent traffic against its copies of a library, as if they
 * blocked, and say what they would have done. The simulation is recorded: it is what
 * lets "Start blocking" through.
 */
export function SimulateLibrary({ library, body, onSimulated }: { library: string; body: unknown; onSimulated?: () => void }) {
  const router = useRouter();
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
            // The library's "Simulation:" line is the server's; read it again so the
            // drawer never says "not simulated yet" beside the numbers just shown.
            router.refresh();
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
export function SimulateThenBlock({ library, body, confirm, simulated = false }: { library: string; body: object; confirm: string; simulated?: boolean }) {
  const [round, setRound] = useState(0);
  // Start blocking is unavailable until a simulation has run (here, or recorded before).
  const ready = simulated || round > 0;
  return (
    <>
      <SimulateLibrary library={library} body={body} onSimulated={() => setRound((r) => r + 1)} />
      <Act key={round} url={`/api/policies/libraries/${library}/mode`} body={{ ...body, mode: "enforce" }} className="k-btn" done="Blocking" confirm={confirm} disabled={!ready} title={ready ? undefined : "Simulate first: it shows what these rules would have stopped."}>
        Start blocking
      </Act>
    </>
  );
}
