"use client";

import { useState } from "react";
import Link from "next/link";
import { AgentLink, Verdict, ts } from "@/components/ui";

/**
 * Unlike Findings, the trace list response doesn't carry decisions/detector_runs
 * (see components/product/ExpandableFindingRow.tsx's comment for the findings side of
 * this) — so opening a row fetches the full trace once, via the client-fetchable
 * /api/traces/[id] proxy, and caches it in state for the rest of the session.
 *
 * Expansion lives on its own <button> (with aria-expanded) and the trace id is a
 * real link to the trace's own page: a click handler on the <tr> alone left this
 * table unreachable by keyboard, and gave a collapsed row no way at all to reach
 * the trace it describes. The row click is kept for mouse users; controls inside
 * it stop propagation.
 */
export function ExpandableTraceRow({ trace, agents }: { trace: any; agents: any[] }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const panelId = `trace-detail-${trace.id}`;

  const toggle = () => {
    setOpen((v) => !v);
    if (!detail && !loading) {
      setLoading(true);
      fetch(`/api/traces/${trace.id}`)
        .then((r) => r.json())
        .then((body) => (body.trace ? setDetail(body) : setError("Could not load this trace's detail.")))
        .catch(() => setError("Could not load this trace's detail."))
        .finally(() => setLoading(false));
    }
  };

  return (
    <>
      <tr onClick={toggle} style={{ cursor: "pointer" }} className={open ? "row-expanded" : undefined}>
        <td className="mono small" style={{ whiteSpace: "nowrap" }}>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggle();
            }}
            aria-expanded={open}
            aria-controls={open ? panelId : undefined}
            aria-label={`${open ? "Hide" : "Show"} decisions for trace ${trace.id}`}
            style={{
              background: "none",
              border: "none",
              padding: 0,
              margin: "0 3px 0 0",
              cursor: "pointer",
              color: "inherit",
              font: "inherit",
              lineHeight: 1,
              verticalAlign: "baseline",
            }}
          >
            <span className="expand-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
          </button>
          <Link href={`/app/traces/${trace.id}`} onClick={(e) => e.stopPropagation()}>
            {trace.id}
          </Link>
        </td>
        <td onClick={(e) => e.stopPropagation()}><AgentLink slug={trace.agent} agents={agents} className="small" /></td>
        <td><Verdict value={trace.verdict} /></td>
        <td className="small muted">{trace.environment}</td>
        <td className="small muted">{trace.model || "—"}</td>
        {/* A ceiling without a floor let this column be starved to 73px on the live
            page, which turned a one-line intent into a 250px-tall row. */}
        <td className="small wrap muted" style={{ minWidth: "20ch", maxWidth: 300 }}>
          {trace.intent || "—"}
        </td>
        <td className="small muted">{ts(trace.started_at)}</td>
      </tr>
      {open && (
        <tr className="row-expanded" id={panelId}>
          <td colSpan={7} style={{ padding: "4px 14px 18px" }}>
            {loading && <p className="small muted">Loading…</p>}
            {error && <p className="small error">{error}</p>}
            {detail && <TraceExpansion detail={detail} />}
            <div style={{ marginTop: 10 }}>
              <Link href={`/app/traces/${trace.id}`} onClick={(e) => e.stopPropagation()}>
                Open full trace →
              </Link>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function TraceExpansion({ detail: d }: { detail: any }) {
  return (
    <div className="stack">
      <div>
        <h3 style={{ margin: "0 0 6px" }}>Decisions</h3>
        {d.decisions.length === 0 ? (
          <p className="small muted">No decisions recorded.</p>
        ) : (
          <div className="panel">
            <table>
              <thead>
                <tr><th>surface</th><th>tool</th><th>verdict</th><th>mode</th><th>rules fired</th></tr>
              </thead>
              <tbody>
                {d.decisions.map((x: any) => (
                  <tr key={x.id}>
                    <td className="small">{x.surface}</td>
                    <td className="mono small">{x.tool || "—"}</td>
                    <td><Verdict value={x.verdict} /></td>
                    <td className="small muted">{x.mode}</td>
                    <td className="small wrap" style={{ maxWidth: 340 }}>
                      {(x.rules_fired || []).length === 0 ? (
                        <span className="muted">none</span>
                      ) : (
                        x.rules_fired.map((r: any, i: number) => (
                          <div key={i} style={{ marginBottom: 4 }}>
                            <span className="mono">{r.rule_id}</span>{" "}
                            <span className="tag">{r.effect}</span>
                            <div className="muted small">{r.reason}</div>
                          </div>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <h3 style={{ margin: "0 0 6px" }}>Detector runs</h3>
        {d.detector_runs.length === 0 ? (
          <p className="small muted">No detector runs recorded.</p>
        ) : (
          <div className="panel">
            <table>
              <thead>
                <tr><th>detector</th><th>surface</th><th>status</th><th className="num">score</th><th>findings</th></tr>
              </thead>
              <tbody>
                {d.detector_runs.map((r: any) => (
                  <tr key={r.id}>
                    <td className="mono small">{r.detector}</td>
                    <td className="small muted">{r.surface}</td>
                    <td><span className={`tag ${r.status === "ok" ? "ok" : "warn"}`}>{r.status}</span></td>
                    <td className="num small">{r.score?.toFixed(2)}</td>
                    <td className="small wrap" style={{ maxWidth: 320 }}>
                      {r.findings.length === 0 ? (
                        <span className="muted">—</span>
                      ) : (
                        r.findings.map((f: any, i: number) => (
                          <div key={i}>
                            <span className="mono">{f.entity_type}</span>{" "}
                            <span className="muted">{f.score?.toFixed(2)}</span>
                            <div className="muted mono" style={{ fontSize: "var(--t-micro)" }}>{f.sample}</div>
                          </div>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
