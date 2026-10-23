import Link from "next/link";
import type { ReactNode } from "react";

/** What a guarded step was, as an event name, in its colour. */
const EVENT: Record<string, { label: string; c: string }> = {
  input: { label: "user_message", c: "var(--af-info)" },
  context: { label: "context_read", c: "var(--af-warn)" },
  tool_args: { label: "tool_call", c: "var(--af-tool)" },
  tool_result: { label: "tool_result", c: "var(--af-tool)" },
  output: { label: "agent_reply", c: "var(--af-ok)" },
};

export function EventBadge({ surface }: { surface?: string }) {
  const e = EVENT[surface ?? ""] ?? { label: surface || "event", c: "var(--af-muted)" };
  return (
    <span className="tag" style={{ ["--c" as string]: e.c }}>
      {e.label}
    </span>
  );
}

/** What AgentFox decided: allowed, held for a person, blocked, masked. */
const VERDICT: Record<string, { label: string; tone: string }> = {
  allow: { label: "allowed", tone: "" },
  escalate: { label: "held", tone: "warn" },
  block: { label: "blocked", tone: "bad" },
  redact: { label: "masked", tone: "info" },
};

export function Verdict({ verdict, would }: { verdict?: string; would?: string | null }) {
  const v = VERDICT[verdict ?? ""] ?? { label: verdict || "—", tone: "" };
  const w = would ? VERDICT[would] : null;
  return (
    <span className="obs-verdict">
      <span className={`tag ${v.tone}`}>{v.label}</span>
      {w && <span className="obs-would" title="What would have happened if this guardrail enforced">would {w.label}</span>}
    </span>
  );
}

export function Time({ at }: { at?: string }) {
  if (!at) return <span className="muted">—</span>;
  const d = new Date(at);
  const today = new Date().toDateString() === d.toDateString();
  return (
    <span className="mono obs-time" title={d.toLocaleString()}>
      {today ? d.toLocaleTimeString([], { hour12: false }) : d.toLocaleDateString([], { month: "short", day: "numeric" })}
    </span>
  );
}

export function AgentLink({ slug }: { slug: string }) {
  return (
    <Link href={`/app/projects/${encodeURIComponent(slug)}`} className="obs-agent">
      {slug}
    </Link>
  );
}

export function SessionId({ id }: { id?: string | null }) {
  if (!id) return <span className="muted">—</span>;
  return (
    <Link href={`/app/escalation/conversations/${encodeURIComponent(id)}`} className="mono obs-session" title={id}>
      {id}
    </Link>
  );
}

/** A Failproof-style list: a hairline table, mono where the value is code. */
export function ObsTable({ head, children, empty }: { head: string[]; children: ReactNode; empty?: ReactNode }) {
  return (
    <div className="obs-table">
      <table>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
      {empty}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="obs-empty">// {children}</p>;
}

export function n(x: number | undefined | null): string {
  return (x ?? 0).toLocaleString();
}
