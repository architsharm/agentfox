/**
 * Product visuals, drawn rather than photographed.
 *
 * Every one of these replaced a screenshot. A 1600px capture of a dense
 * governance dashboard, shrunk into a 600px column, is a picture of a document:
 * a sidebar, a paragraph of help text, a filter row and a seven-column table, at
 * a size where none of it can be read and nothing draws the eye. It proves a
 * product exists and communicates nothing about what it does.
 *
 * These are DOM instead, which buys four things a raster cannot:
 *
 *   - Type stays legible at whatever size the section gives it, because it is
 *     type rather than pixels.
 *   - One thing can be emphasised. A screenshot has no focal point; these each
 *     have exactly one, and the rest is deliberately quiet around it.
 *   - They follow the theme. A light capture on a dark page was a white slab.
 *   - They can move, in the one place motion earns its keep: the moment a
 *     verdict lands.
 *
 * What they are NOT is a mock-up of a screen that does not exist. Every value
 * below was read off this repository's own gateway running the seeded demo, the
 * same way the decision cards were: `kb.search` allows, `payments.transfer`
 * blocks on `capability.denied`, `tickets.update` with a wildcard blocks on two
 * rules. The composition is curated; the content is not invented.
 */

import type { ReactNode } from "react";

/* --- Frame ---------------------------------------------------------------- */

/** The shared surface. A soft window rather than a browser chrome with dots —
 *  the dots were pretending these are screenshots, and they are not. */
export function Pane({
  label,
  status,
  children,
  tight = false,
}: {
  label: string;
  status?: string;
  children: ReactNode;
  tight?: boolean;
}) {
  return (
    <div className="pv">
      <div className="pv-bar">
        <span className="pv-bar-label">{label}</span>
        {status && (
          <span className="pv-live">
            <i />
            {status}
          </span>
        )}
      </div>
      <div className={tight ? "pv-body pv-body-tight" : "pv-body"}>{children}</div>
    </div>
  );
}

/* --- 1. The decision stream (hero) ---------------------------------------- */

type Call = {
  tool: string;
  arg: string;
  verdict: "allow" | "block";
  /** Only the focal row carries these. */
  rule?: string;
  reason?: string;
};

/** Four calls from one agent. Three are the job; one is the thing that matters. */
const STREAM: Call[] = [
  { tool: "kb.search", arg: 'q: "refund policy"', verdict: "allow" },
  { tool: "crm.lookup", arg: "customer: cus_882", verdict: "allow" },
  {
    tool: "payments.transfer",
    arg: "amount: 5000  to: acct_x",
    verdict: "block",
    rule: "capability.denied",
    reason: "No capability grants this agent the requested tool and action.",
  },
  { tool: "tickets.create", arg: "order: #4471", verdict: "allow" },
];

/**
 * The hero. It answers "what does this thing do" in one look: most of what the
 * agent does goes through, one thing does not, and the reason is right there.
 *
 * The blocked row is the third of four on purpose. First would read as a demo
 * built to fail; last would read as a conclusion. In the middle it reads as what
 * it is — one call among several, caught on the way past.
 */
export function DecisionStream() {
  return (
    <Pane label="support-triage" status="governed">
      <div className="pv-stream">
        {STREAM.map((c, i) => (
          <div
            key={c.tool}
            className={c.verdict === "block" ? "pv-call pv-call-stop" : "pv-call"}
            /* 0.16s apart, not 0.09: at the old spacing all four rows arrived
               inside a quarter second and there was no sequence to read. The
               refusal is the fourth beat and gets the extra pause before it. */
            style={{ animationDelay: `${0.18 + i * 0.16 + (c.verdict === "block" ? 0.1 : 0)}s` }}
          >
            <div className="pv-call-head">
              <span className="pv-tool">{c.tool}</span>
              <span className="pv-arg">{c.arg}</span>
              <span className={c.verdict === "block" ? "pv-v pv-v-stop" : "pv-v pv-v-go"}>
                {c.verdict}
              </span>
            </div>
            {c.rule && (
              <div className="pv-call-why">
                <span className="pv-rule">{c.rule}</span>
                <span className="pv-reason">{c.reason}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </Pane>
  );
}

/* --- 2. One request, taken apart ------------------------------------------ */

const SPANS: [string, string, string][] = [
  ["guard.input", "allow", "3.0ms"],
  ["retrieval", "allow", "11.4ms"],
  ["guard.tool_result", "block", "4.1ms"],
];

const PROVENANCE: [string, string, "user" | "tool_result"][] = [
  ["$.messages[0].content", "user", "user"],
  ["$.messages[1].content", "tool_result", "tool_result"],
];

/**
 * The evidence visual. The screenshot this replaced showed the same information
 * and put the interesting part — two untrusted values and a blocked tool result
 * — in 8px grey type in the lower right.
 */
export function TraceAnatomy() {
  return (
    <Pane label="trc_01m39as4ee7w539tc6" status="recorded">
      <div className="pv-trace-title">summarise the Q3 refunds document</div>
      <div className="pv-grid2">
        <div>
          <span className="pv-h">Timeline</span>
          {SPANS.map(([name, v, ms]) => (
            <div key={name} className="pv-span">
              <span className="pv-tool">{name}</span>
              <span className={v === "block" ? "pv-v pv-v-stop" : "pv-v pv-v-go"}>{v}</span>
              <span className="pv-ms">{ms}</span>
            </div>
          ))}
        </div>
        <div>
          <span className="pv-h">Where each value came from</span>
          {PROVENANCE.map(([path, src]) => (
            <div key={path} className="pv-span">
              <span className="pv-tool">{path}</span>
              <span className="pv-arg">{src}</span>
              <span className="pv-v pv-v-hold">untrusted</span>
            </div>
          ))}
        </div>
      </div>
      <div className="pv-note">
        <span className="pv-rule">injection.indirect</span>
        <span className="pv-reason">
          Instruction-like content found in untrusted retrieved or tool content.
        </span>
      </div>
    </Pane>
  );
}

/* --- 3. What a scan finds ------------------------------------------------- */

const TILES: [string, string, "ok" | "stop" | "hold" | "flat"][] = [
  ["4", "agents", "flat"],
  ["1", "unregistered", "stop"],
  ["2", "no owner", "hold"],
  ["16", "tools", "flat"],
];

/** The discovery visual: four counts, and the one row that is the point. */
export function EstateScan() {
  return (
    <Pane label="Agent registry" status="from traffic">
      <div className="pv-tiles">
        {TILES.map(([n, label, tone]) => (
          <div key={label} className={`pv-tile pv-tile-${tone}`}>
            <b>{n}</b>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <div className="pv-found">
        <div className="pv-call-head">
          <span className="pv-tool">marketing-copy-bot</span>
          <span className="pv-arg">production · echo-1 · 1 call</span>
          <span className="pv-v pv-v-stop">never registered</span>
        </div>
        <div className="pv-call-why">
          <span className="pv-reason">
            Observed in traffic. Nobody declared it, so nobody owns what it does.
          </span>
        </div>
      </div>
    </Pane>
  );
}
