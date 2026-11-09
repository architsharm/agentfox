"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Card, Empty, Pill } from "@/components/kit";
import { plainError, runRow, type Run } from "@/lib/product/attackTest";
import { projectHref } from "@/lib/product/project";

type Agent = { slug: string; name?: string };
type Listed = Run & { project: string; createdAt?: string; agents?: { slug: string; name: string }[] };

/**
 * Testing → Attack tests: the attack test each agent's page runs, and its history.
 *
 * It used to be a second, different test (a built-in library run on the server, with
 * its own numbers) next to a list that never showed the agent pages' runs. Run here
 * starts the same test the agent's panel starts (on the agent, through its
 * `agentfox init`), and the list is those runs, with the panel's numbers.
 */
export function AttackRuns({ agents }: { agents: Agent[] }) {
  const [agent, setAgent] = useState("");
  const [runs, setRuns] = useState<Listed[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/onboarding/runs${agent ? `?agent=${encodeURIComponent(agent)}` : ""}`, { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(plainError(data?.detail) || `Something went wrong (${res.status}).`);
      setRuns(data.runs || []);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [agent]);

  useEffect(() => {
    load();
  }, [load]);
  // While a run is going, watch it.
  const going = (runs || []).some((r) => r.status === "running");
  useEffect(() => {
    if (!going) return;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }, [going, runs, load]);

  const run = async () => {
    if (!agent) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/onboarding/agents/${encodeURIComponent(agent)}/tests`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(plainError(data?.detail) || `Something went wrong (${res.status}).`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false); // the chosen agent stays chosen
    }
  };

  return (
    <>
      <Card
        title="Run the attack test"
        hint="Sends the attack library to the real agent through agentfox init on your machine, with every tool faked: the same test as the agent page's panel. A clean run means these attacks were stopped, not that every attack would be."
      >
        <div className="k-pills" style={{ gap: 8 }}>
          <select className="k-select" value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Agent">
            <option value="">Every agent</option>
            {agents.map((a) => (
              <option key={a.slug} value={a.slug}>
                {a.name || a.slug}
              </option>
            ))}
          </select>
          <button type="button" className="k-btn-primary" onClick={run} disabled={!agent || busy || going} title={agent ? undefined : "Choose an agent"}>
            Run
          </button>
        </div>
        {error ? <p className="k-muted small" role="alert">{error}</p> : null}
      </Card>
      <Card title="Past runs" flush>
        {runs === null ? (
          <Empty>Loading…</Empty>
        ) : runs.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Agents</th>
                <th className="tight">Guardrails</th>
                <th className="num">Attacks</th>
                <th className="num">Stopped</th>
                <th className="num">Got through</th>
                <th>Normal requests</th>
                <th className="tight">When</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const n = runRow(r);
                const names = (r.agents || []).map((a) => a.name || a.slug);
                const first = r.agents?.[0]?.slug;
                return (
                  <tr key={r.id}>
                    <td>
                      {first ? <Link className="k-name" href={projectHref(first, "canvas")}>{names.join(", ")}</Link> : names.join(", ") || r.project}
                      {n.notRun || n.errored ? (
                        <span className="sub">{[n.notRun ? `${n.notRun} not run` : "", n.errored ? `${n.errored} errored` : ""].filter(Boolean).join(" · ")}</span>
                      ) : null}
                    </td>
                    <td className="tight">{r.phase === "after" ? "With guardrails" : "None"}</td>
                    <td className="num">{n.attacks}</td>
                    <td className="num">{n.state === "running" ? "…" : n.ran ? n.stopped : "—"}</td>
                    <td className="num">
                      {n.state === "running" ? "Running" : !n.ran ? "Not run" : n.through ? <Pill tone="bad">{n.through}</Pill> : "0"}
                    </td>
                    <td>{n.normal ?? "—"}</td>
                    <td className="tight muted">{r.createdAt ? new Date(r.createdAt).toLocaleString() : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <Empty>No attack tests yet. Run agentfox init in an agent&apos;s repository; its first test starts by itself.</Empty>
        )}
      </Card>
    </>
  );
}
