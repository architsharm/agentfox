"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

type Result = { id: string; sample: string; surface: string; fires: boolean; fired: boolean | null; passed: boolean; trace_id: string | null };

/**
 * Messages this rule must catch, and ones it must leave alone. Each is re-checked
 * against every proposed change on the Tune tab, before anything is applied.
 */
export function RuleTests({ ruleId, results, agents }: { ruleId: string; results: Result[]; agents: string[] }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [surface, setSurface] = useState("input");
  const [agent, setAgent] = useState(agents[0] || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const base = `/api/rules/${encodeURIComponent(ruleId)}/examples`;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      router.refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const add = (fires: boolean) =>
    run(async () => {
      await callJson(base, "POST", { text, surface, agent, fires });
      setText("");
    });

  return (
    <div className="k-form">
      {results.length > 0 && (
        <table className="k-table">
          <tbody>
            {results.map((r) => (
              <tr key={r.id}>
                <td className="tight">
                  <span className={`k-pill ${r.passed ? "k-pill-ok" : "k-pill-bad"}`}>{r.passed ? "Pass" : r.fired === null ? "Missing" : "Fail"}</span>
                </td>
                <td>
                  <span className="k-name">{r.sample || "(no text)"}</span>
                  <span className="sub">{r.fires ? "Should fire" : "Should not fire"}</span>
                </td>
                <td className="tight">
                  {r.trace_id && (
                    <Link className="k-muted" href={`/app/traces/${r.trace_id}`}>
                      Run
                    </Link>
                  )}
                </td>
                <td className="tight">
                  <button className="k-btn-ghost" disabled={busy} onClick={() => run(() => callJson(`${base}/${encodeURIComponent(r.id)}`, "DELETE"))}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
        {agents.length > 1 && (
          <select className="k-select" value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Agent">
            {agents.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        )}
        <div className="k-seg" role="group" aria-label="Where">
          {[
            ["input", "User message"],
            ["output", "Agent reply"],
          ].map(([k, label]) => (
            <button key={k} className={surface === k ? "active" : ""} onClick={() => setSurface(k)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <textarea className="k-input" rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="A message this rule should, or should not, catch" aria-label="Test text" />
      <div className="k-pills" style={{ gap: 8 }}>
        <button className="k-btn-primary" disabled={busy || !text.trim() || !agent} onClick={() => add(true)}>
          Should fire
        </button>
        <button className="k-btn" disabled={busy || !text.trim() || !agent} onClick={() => add(false)}>
          Should not fire
        </button>
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}
