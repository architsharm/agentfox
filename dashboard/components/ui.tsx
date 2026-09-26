/** Shared presentational pieces. */

import Link from "next/link";
import { InfoTip } from "./InfoTip";

export { InfoTip } from "./InfoTip";

/**
 * Every agent has a real display name (e.g. "Payments Operations Agent") — the
 * registry slug (`payments-ops`) is still needed for the URL and for cross-
 * referencing logs, but a non-technical reader shouldn't have to see it as the
 * primary label. Pass the already-fetched agents list so this needs no extra
 * request; falls back to the slug if the agent isn't found in it.
 */
/**
 * The display name for a slug, for the places that need the text without a link
 * (a filter chip, a sentence). Same rule as `AgentLink`: show what a person
 * named the agent, fall back to the slug when there is nothing better.
 */
export function agentName(
  agents: { agents?: { slug: string; name?: string }[] } | { slug: string; name?: string }[] | null | undefined,
  slug: string,
): string {
  const list = Array.isArray(agents) ? agents : agents?.agents || [];
  return list.find((a) => a.slug === slug)?.name || slug;
}

export function AgentLink({
  slug,
  agents,
  className,
}: {
  slug: string;
  agents: { slug: string; name?: string }[];
  className?: string;
}) {
  const name = agents.find((a) => a.slug === slug)?.name;
  return (
    <Link href={`/app/agents/${slug}`} className={className} title={name ? slug : undefined}>
      {name || slug}
    </Link>
  );
}

export function Stat({
  n,
  label,
  tone,
  hint,
}: {
  n: React.ReactNode;
  label: string;
  tone?: "ok" | "warn" | "bad";
  /** Explains a number whose formula isn't obvious from the label alone — shown as
   * a native tooltip so the card stays compact. */
  hint?: string;
}) {
  return (
    <div className={`card${tone ? " " + tone : ""}`}>
      <div className="n">{n}</div>
      <div className="l">
        {label}
        {hint && <InfoTip text={hint} />}
      </div>
    </div>
  );
}

/** A `Stat` that goes somewhere — the number is the summary, the link is where
 * to go to see the rows that make it up. */
export function StatLink({
  n,
  label,
  tone,
  href,
  hint,
}: {
  n: React.ReactNode;
  label: string;
  tone?: "ok" | "warn" | "bad";
  href: string;
  hint?: string;
}) {
  return (
    <Link href={href} className={`card link${tone ? " " + tone : ""}`}>
      <div className="n">{n}</div>
      <div className="l">
        {label}
        {hint && <InfoTip text={hint} />}
      </div>
    </Link>
  );
}

export function Panel({
  title,
  note,
  children,
}: {
  title: string;
  note?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="panel">
      <div className="head">
        <span>{title}</span>
        {note && <span className="note">{note}</span>}
      </div>
      {children}
    </div>
  );
}

const VERDICT_TONE: Record<string, string> = {
  block: "bad",
  escalate: "escalate",
  redact: "warn",
  mask: "warn",
  tokenize: "warn",
  allow: "ok",
};

/**
 * What happened to the call at the boundary — drawn, then named.
 *
 * A verdict was a coloured pill, which is the same shape this product uses for
 * a tier, a status, a mode and a framework. In a table of fifty rows the one
 * column that carries the actual decision looked like every other chip on the
 * page, and the reader had to read the word to know what they were looking at.
 *
 * These are the hero's vocabulary at row scale: a track meeting a checkpoint,
 * and what became of it. Crossed with an arrow, stopped at a bar, held at the
 * line for a person, or crossed altered. Four outcomes, four silhouettes, so a
 * column of them is scannable before any word is read.
 *
 * The word stays. A glyph on its own is a puzzle, and this is a governance
 * record — the row has to say what it means in language, not only in shape.
 */
const VERDICT_SHAPE: Record<string, "through" | "stop" | "hold" | "altered"> = {
  allow: "through",
  block: "stop",
  escalate: "hold",
  redact: "altered",
  mask: "altered",
  tokenize: "altered",
};

function VerdictGlyph({ shape }: { shape: "through" | "stop" | "hold" | "altered" }) {
  // 34x14. The gate sits at x=19 in every one of them, so a column of these
  // lines up on the boundary and the eye reads the difference, not the drift.
  return (
    <svg className="vg" viewBox="0 0 34 14" width="34" height="14" aria-hidden focusable="false">
      {/* approach — identical in all four */}
      <line x1="1" y1="7" x2="19" y2="7" className="vg-in" />
      {/* the boundary */}
      <line x1="19" y1="2.5" x2="19" y2="11.5" className="vg-gate" />

      {shape === "through" && (
        <>
          <line x1="19" y1="7" x2="29" y2="7" className="vg-out" />
          <path d="M26.5 4.5 L30 7 L26.5 9.5" className="vg-head" />
        </>
      )}
      {shape === "altered" && (
        <>
          {/* It crossed, but not unchanged: the dash is the alteration. */}
          <line x1="19" y1="7" x2="29" y2="7" className="vg-out vg-dash" />
          <path d="M26.5 4.5 L30 7 L26.5 9.5" className="vg-head" />
        </>
      )}
      {shape === "stop" && <line x1="21" y1="3" x2="21" y2="11" className="vg-bar" />}
      {shape === "hold" && (
        /* Held at the line waiting for a person — an open ring, not a bar:
           nothing has been decided yet. */
        <circle cx="24" cy="7" r="3" className="vg-hold" />
      )}
    </svg>
  );
}

export function Verdict({ value }: { value?: string | null }) {
  if (!value) return <span className="muted">—</span>;
  const shape = VERDICT_SHAPE[value];
  const tone = VERDICT_TONE[value] || "";
  if (!shape) return <span className={`tag ${tone}`}>{value}</span>;
  return (
    <span className={`verdict verdict-${tone}`}>
      <VerdictGlyph shape={shape} />
      <span>{value}</span>
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  effective: "ok",
  degraded: "warn",
  failing: "bad",
  not_implemented: "",
  not_applicable: "",
  not_computed: "",
};

export function ControlStatus({ value }: { value: string }) {
  return <span className={`tag ${STATUS_TONE[value] ?? ""}`}>{value.replace(/_/g, " ")}</span>;
}

/**
 * A bare control code ("NOM-RTG-09") means nothing to a reader who hasn't
 * memorized the catalog — every place one renders links to its full record on
 * the Compliance page, so `titles` (from `controlTitleMap()`, lib/controls.ts)
 * gets shown alongside it, not just on hover. The code leads, compact and
 * mono, since that's the part someone cross-referencing several controls at
 * once actually scans for; the title trails as a single truncated line —
 * control titles are full sentences written for their own dedicated column on
 * the Compliance page, and several of those stacked verbatim in a narrow
 * table cell (a finding can carry two or three) overwhelmed the row they sat
 * in. The full sentence is still one hover away via the native `title`
 * attribute, and a code missing from the map still shows the code rather than
 * nothing.
 */
/**
 * One mapped control, as a chip.
 *
 * It used to render the code followed by the control's title, ellipsised at
 * 260px. In a Findings row that column is far narrower than 260, so the title
 * arrived as four words and a full stop that is not a full stop — "Personal and
 * sensitive data is de…" — stacked two deep, on every row. Truncated prose in a
 * dense table is worse than no prose: it costs a line, reads as broken, and the
 * reader still has to hover to learn anything.
 *
 * The code is the part people act on and quote, so the code is what shows. The
 * title stays as the tooltip it already was, and the chip links to the control.
 */
export function ControlChip({ code, titles }: { code: string; titles: Record<string, string> }) {
  const title = titles[code];
  return (
    <Link href={`/app/compliance#${code}`} title={title || code} className="ctrl-chip">
      {code}
    </Link>
  );
}


const SEVERITY_TONE: Record<string, string> = {
  critical: "bad",
  high: "bad",
  medium: "warn",
  low: "",
};

export function Severity({ value }: { value: string }) {
  return <span className={`tag ${SEVERITY_TONE[value] ?? ""}`}>{value}</span>;
}

/**
 * A finding's raw `type` ("redteam", "shadow_agent", "mcp_schema_drift", ...) is an
 * internal slug, not a sentence a reader has met before — shown bare, a queue of
 * findings reads as jargon with no way to tell at a glance what kind of problem
 * each row is. This maps every type this product raises to a short plain-English
 * label and, optionally, a one-line "what this means" — falling back to a
 * humanized version of the slug for anything not explicitly listed, so nothing
 * ever renders as raw underscored jargon with zero explanation.
 */
const FINDING_TYPE_INFO: Record<string, { label: string; blurb?: string }> = {
  guardrail_detection: { label: "Guardrail catch", blurb: "A detector caught something in a request or response and it changed the outcome — see the masked excerpt below." },
  redteam: { label: "Security test", blurb: "Simulated attacks got through without being blocked." },
  // Was absent, so it rendered through the humanize fallback as the bare slug
  // "redteam over block" — which reads as a typo rather than as a category.
  redteam_over_block: { label: "Over-blocking", blurb: "The agent refused legitimate requests from the test's control group — a guardrail that blocks real work gets switched off." },
  shadow_agent: { label: "Unregistered agent", blurb: "This agent is sending traffic but was never registered." },
  unowned_agent: { label: "No owner", blurb: "No one is accountable for this agent's decisions." },
  missed_escalation: { label: "Missed hand-off", blurb: "A conversation should have gone to a human and didn't." },
  handoff_sla_breach: { label: "Hand-off overdue", blurb: "A human hand-off has gone unacknowledged past its deadline." },
  incomplete_handoff: { label: "Incomplete hand-off", blurb: "Context the next step needed was missing when work was handed off." },
  false_resolution: { label: "False resolution", blurb: "Marked resolved without actually resolving the user's issue." },
  boundary_breach: { label: "Answered outside its boundary", blurb: "The agent answered beyond the knowledge boundary it declared." },
  budget_breach: { label: "Budget exceeded", blurb: "This agent has exceeded its configured cost or call budget." },
  budget_exhausted: { label: "Budget exhausted", blurb: "This agent has used up its configured cost or call budget." },
  agent_stopped: { label: "Agent stopped", blurb: "Traffic was halted by a kill switch or quarantine." },
  registry_drift: { label: "Registry drift", blurb: "What this agent actually calls no longer matches what it declared." },
  undeclared_mcp_tool: { label: "Undeclared tool use", blurb: "The agent called a tool it never declared using." },
  mcp_schema_drift: { label: "Tool contract changed", blurb: "A tool's schema changed after approval — possible tampering." },
  over_refusal: { label: "Over-refusal", blurb: "The agent is refusing requests it should be able to answer." },
  drift: { label: "Model drift", blurb: "This model's outputs have measurably changed from its baseline." },
  entitlement_disclosure: { label: "Disclosure risk", blurb: "May have disclosed something the requester wasn't entitled to see." },
  aggregation_disclosure: { label: "Disclosure risk", blurb: "Combined otherwise-safe facts into something the requester shouldn't see." },
  inference_disclosure: { label: "Disclosure risk", blurb: "Let the requester infer something they weren't entitled to know." },
  fabricated_citation: { label: "Fabricated citation", blurb: "Cited a source that doesn't say what it claims, or doesn't exist." },
  integrity_error: { label: "Data integrity error", blurb: "A numeric, temporal, or identity error was detected in the output." },
  schema_drift: { label: "Schema drift", blurb: "A data source's structure changed unexpectedly." },
  source_authority: { label: "Untrusted source", blurb: "Used a source below the trust tier this required." },
  source_conflict: { label: "Conflicting sources", blurb: "Two sources disagreed and the conflict wasn't surfaced." },
  tool_poisoning: { label: "Tool poisoning", blurb: "A tool's behavior changed in a way that looks like tampering." },
  unpinned_server: { label: "Unpinned MCP server", blurb: "Not pinned to a known-good version." },
};

export function findingTypeInfo(type: string): { label: string; blurb?: string } {
  return FINDING_TYPE_INFO[type] || { label: type.replace(/_/g, " ") };
}

export function FindingType({ value }: { value: string }) {
  const info = findingTypeInfo(value);
  return <span title={info.blurb}>{info.label}</span>;
}

/**
 * The draft-mapping warning. Rendered next to every compliance claim, deliberately:
 * a product that presents unreviewed regulatory mappings as authoritative fails its
 * first serious audit conversation (Appendix B §B.6).
 */
/**
 * That the framework mappings are unreviewed.
 *
 * This was an amber warning panel with a shouted heading ("Framework mappings
 * are DRAFT") and three sentences of hedging, at the top of the page, on every
 * load. Every word of it was true and none of it needed that much volume: a
 * warning box the reader sees every single time is a banner they stop reading,
 * and shouting a disclaimer reads as less confident, not more careful.
 *
 * One line, in the page's own voice, with the precise wording — which matters,
 * because it is what an evidence package is stamped with — kept in full on the
 * tooltip. Same information, same honesty, said once.
 */
const DRAFT_DETAIL =
  "They have not been reviewed by compliance counsel or a certification body, and they are not legal advice. Evidence packages built from them are stamped DRAFT — UNVERIFIED / NOT LEGAL ADVICE until a named reviewer confirms each mapping.";

export function DraftCaveat({ text }: { text?: string }) {
  return (
    <p className="draft-note">
      <span className="draft-tag">Draft</span>
      {text ? (
        <>
          {text}
          <InfoTip text={DRAFT_DETAIL} />
        </>
      ) : (
        <>
          Framework mappings are engineering&rsquo;s reading of the published texts, not
          a reviewed compliance{" "}
          {/* The final word and the tooltip are bound together: on its own the ⓘ
              wrapped to a line of its own under the sentence and read as a stray
              glyph rather than as part of it. */}
          <span className="nowrap">
            opinion.
            <InfoTip text={DRAFT_DETAIL} />
          </span>
        </>
      )}
    </p>
  );
}

/**
 * What this product does not cover, per framework.
 *
 * Kept, because a compliance page that only lists what it does cover is the
 * dishonest version — but behind a control rather than stacked loose under the
 * frameworks table as a run of bare <h3>s and bullet lists. Someone reading
 * coverage should be able to reach the gaps in one click and not have to scroll
 * past them to leave.
 */
export function Gaps({ gaps, title }: { gaps: string[]; title?: string }) {
  if (!gaps?.length) return null;
  return (
    <details className="rt-more" style={{ marginTop: 14 }}>
      <summary>
        {title ? `${title}: ` : ""}
        {gaps.length} thing{gaps.length === 1 ? "" : "s"} this product does not cover
      </summary>
      <ul className="gaps-list">
        {gaps.map((g) => (
          <li key={g}>{g}</li>
        ))}
      </ul>
    </details>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="body muted small">{children}</div>
  );
}

/**
 * True only where someone can actually act on "run `agentfox serve`" — i.e. the
 * control plane is a process on their own machine or in their own deployment.
 *
 * `NOMETRIA_SELF_HOSTED` is the explicit switch; with it unset we infer from
 * whether the configured API URL is a loopback address, which is exactly the
 * local-dev case and never the hosted one. The default direction matters: on the
 * hosted deployment nobody can run that command, so telling them to is worse
 * than saying nothing.
 *
 * Read inside the render (not at module scope) so it follows the running
 * process's environment rather than whatever was set when the bundle was built.
 */
function isSelfHosted(): boolean {
  const flag = process.env.NOMETRIA_SELF_HOSTED;
  if (flag !== undefined && flag !== "") return /^(1|true|yes)$/i.test(flag);
  const url = process.env.NOMETRIA_API_URL;
  if (!url) return true; // no URL configured at all means the built-in localhost default
  return /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/i.test(url);
}

/**
 * What a page shows when its control-plane fetch came back not-ok.
 *
 * It used to say "API unreachable, start it with `agentfox serve`" for every
 * status, which is wrong twice over: an expired session is a 401 from a server
 * that is plainly running, and on the hosted deployment nobody has a server to
 * start. So the status picks the sentence, and the self-host hint is shown only
 * where it is actionable.
 */
export function ApiDown({ error, status }: { error: string; status?: number }) {
  if (status === 401 || status === 403) {
    const revoked = status === 403;
    return (
      <div className="error">
        <strong>{revoked ? "This session is not allowed to see that." : "Your session has expired."}</strong>
        <div className="small" style={{ marginTop: 6 }}>
          {revoked ? (
            <>
              The control plane is up and recognised you, but rejected this request.
              Either your access was changed, or this workspace is not yours to read.
              Signing in again picks up any new access.
            </>
          ) : (
            <>The control plane no longer accepts this sign-in. Signing in again fixes it.</>
          )}{" "}
          <Link href="/login?session=expired">Sign in again</Link>.
        </div>
      </div>
    );
  }

  if (status === 404) {
    return (
      <div className="error">
        <strong>The control plane has no such record.</strong>
        <div className="small" style={{ marginTop: 6 }}>
          The server answered normally, it just has nothing at this address. The link
          may be stale, or nothing has created this yet.
        </div>
        <div className="small mono muted" style={{ marginTop: 8 }}>
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="error">
      <strong>
        {status && status >= 500
          ? "The control plane returned an error."
          : "Control-plane API unreachable."}
      </strong>
      <div className="small" style={{ marginTop: 6 }}>
        {status && status >= 500 ? (
          <>Nothing on this page is missing because of anything you did. Reload in a
          moment; if it keeps happening the control plane needs a look.</>
        ) : (
          <>The dashboard could not reach the control plane at all. Reload once it is back.</>
        )}
        {isSelfHosted() && (
          <>
            {" "}
            Start it with <code className="mono">agentfox serve</code>, then reload. Set{" "}
            <code className="mono">NOMETRIA_API_URL</code> if it is not on{" "}
            <code className="mono">http://127.0.0.1:8080</code>.
          </>
        )}
      </div>
      <div className="small mono muted" style={{ marginTop: 8 }}>
        {error}
      </div>
    </div>
  );
}

/**
 * The other half of the not-ok-response story: the server answered fine, it just
 * doesn't have this row. Confusing this with `ApiDown` sends a reader toward
 * "restart the server" for a problem that isn't the server — a stale link, a
 * record that was never created, an id that got typo'd.
 */
export function NotFound({
  what,
  detail,
  back,
}: {
  /** What kind of thing is missing, lowercase — "finding", "trace", "run". */
  what: string;
  detail?: string;
  back?: { href: string; label: string };
}) {
  return (
    <div className="hero empty">
      <div className="hero-title">No such {what}</div>
      <p>
        The control plane is up — it just doesn&rsquo;t have a {what} at this id. The
        link may be stale, or nothing has created one yet.
      </p>
      {detail && <p className="small muted mono">{detail}</p>}
      {back && (
        <p>
          <Link href={back.href}>&larr; {back.label}</Link>
        </p>
      )}
    </div>
  );
}

export function ts(value?: string | null) {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 19);
}

export function pct(value?: number | null) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/**
 * Inventory as a strip, not as tiles.
 *
 * The Overview had nine equally-weighted stat tiles in two rows. The first four
 * answer "what needs me today"; the next five answer "what exists". Those are
 * different kinds of question, and giving them the same treatment made the page
 * read as a wall of numbers with no order to it — the single most recognisable
 * shape of a generated dashboard.
 *
 * So the first row stays as tiles, because that IS the point of the page, and
 * this becomes one hairline row underneath. A figure only takes colour when it
 * is a problem: `0 unregistered` is not news and should not glow.
 */
export function InventoryStrip({
  items,
}: {
  items: { n: React.ReactNode; label: string; href: string; tone?: "warn" | "bad" }[];
}) {
  return (
    <div className="inv-strip">
      {items.map((it) => (
        <Link key={it.label} href={it.href} className={it.tone ? `inv-item inv-${it.tone}` : "inv-item"}>
          <b>{it.n}</b>
          <span>{it.label}</span>
        </Link>
      ))}
    </div>
  );
}

/**
 * Tool-call arguments, as pairs rather than as JSON.
 *
 * The Approvals table rendered `JSON.stringify(args)` into a 260px monospace
 * cell with wrapping on, which broke values mid-token: an approver deciding
 * whether to release money saw `"to":"acct_att acker_99i"` across two lines.
 * A destination account split by a line wrap is the single worst thing this
 * table could do, because the whole page exists for a human to check exactly
 * that value before saying yes.
 *
 * One pair per row, key muted and value whole. A value long enough to need a
 * break gets one at a character boundary rather than wherever the wrap landed,
 * and the row can scroll rather than fold.
 */
export function ArgsCell({ args }: { args: Record<string, unknown> | null | undefined }) {
  const entries = args ? Object.entries(args) : [];
  if (!entries.length) return <span className="muted">—</span>;
  return (
    <dl className="args">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * A breakdown of one total, drawn to scale.
 *
 * Compliance showed 35 effective / 3 degraded / 2 failing / 2 not implemented /
 * 0 not computed / 88% as six equally-weighted tiles. Five of those are parts of
 * one whole and the sixth is derived from them, so the page spent its entire
 * first screen restating a single fact six ways with no sense of proportion —
 * you could not tell at a glance whether 3 degraded was most of the estate or
 * almost none of it.
 *
 * One bar answers that. The segments are to scale, the legend carries the exact
 * counts, and the ratio that matters gets stated once beside it rather than
 * competing as a seventh box. This is the same treatment the public benchmark
 * page uses for the AgentDojo composition, for the same reason.
 */
export function StatusBar({
  segments,
  total,
  unit,
}: {
  segments: { n: number; label: string; tone: "ok" | "warn" | "bad" | "idle" }[];
  total?: React.ReactNode;
  unit?: string;
}) {
  const sum = segments.reduce((a, s) => a + s.n, 0) || 1;
  const shown = segments.filter((s) => s.n > 0);
  return (
    <div className="sbar-wrap">
      <div className="sbar" role="img" aria-label={segments.map((s) => `${s.n} ${s.label}`).join("; ")}>
        {shown.map((s) => (
          <span
            key={s.label}
            className={`sbar-seg sbar-${s.tone}`}
            style={{ flex: `${s.n} 0 0` }}
            title={`${s.n} ${s.label}`}
          />
        ))}
      </div>
      <ul className="sbar-key">
        {segments.map((s) => (
          <li key={s.label} className={s.n ? undefined : "sbar-zero"}>
            <i className={`sbar-${s.tone}`} aria-hidden />
            <b>{s.n}</b>
            <span>{s.label}</span>
          </li>
        ))}
      </ul>
      {total != null && (
        <p className="sbar-total">
          <b>{total}</b> {unit}
        </p>
      )}
    </div>
  );
}
