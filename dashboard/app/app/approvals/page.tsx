import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, safeApi, apiErrorProps } from "@/lib/api";
import { AgentLink, ApiDown, ArgsCell, Empty, InfoTip, InventoryStrip, Severity, ts } from "@/components/ui";
import { PageHeader } from "@/components/PageHeader";
import { Countdown } from "@/components/Countdown";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata(
  "Approvals",
  "Actions held for a human decision, and the escalation queue.",
);

export const dynamic = "force-dynamic";

const STATUSES = ["pending", "approved", "denied", "expired", "used"];
const TABS: { key: string; label: string }[] = [
  { key: "approvals", label: "Approvals" },
  { key: "escalation", label: "Escalation" },
];

/**
 * `reason` is every fired rule's reason joined with "; " — three or four full
 * sentences is normal. Showing all of them inline blows one row out to seven
 * lines next to five one-line columns. Show the first rule's reason (the one
 * that actually decided the verdict) and a count for the rest, full text on
 * hover — the same "summary visible, detail on demand" split the table uses
 * for arguments (truncated + monospace) already, just applied here too.
 */
/**
 * Why this call needs a person, in full.
 *
 * This showed the first semicolon-separated part truncated to one line at 280px,
 * with the rest behind a "+2 more" chip and the whole thing behind a tooltip.
 * Each part is a separate rule that fired, and on this page the reason is the
 * second most important thing after the arguments — it is what the approver is
 * deciding against. Hiding two thirds of it behind a hover on the page where
 * someone releases money is the wrong trade for one line of height.
 */
function ReasonCell({ reason }: { reason?: string }) {
  if (!reason) return <span className="muted">—</span>;
  const parts = reason.split(/;\s*/).filter(Boolean);
  return (
    <ul className="reasons">
      {parts.map((part) => (
        <li key={part}>{part}</li>
      ))}
    </ul>
  );
}

/**
 * Approvals and Escalation are two parallel "a human has to act" queues —
 * one tool call needing sign-off, one whole conversation needing a hand-off —
 * that used to be two sidebar items. Same page now, tabs, same distinction
 * spelled out in the intro so nobody confuses one for the other.
 */
export default async function Approvals({
  searchParams,
}: {
  searchParams: Promise<{
    tab?: string;
    status?: string;
    agent?: string;
    review_error?: string;
    review_notice?: string;
  }>;
}) {
  const { tab: rawTab, status, agent, review_error, review_notice } = await searchParams;
  const tab = TABS.some((t) => t.key === rawTab) ? rawTab! : "approvals";

  return (
    <>
      <PageHeader title="Approvals" sub="Requests waiting on a person: one tool call, or a whole conversation." />

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      <div className="tabbar">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={t.key === "approvals" ? "/app/approvals" : `/app/approvals?tab=${t.key}`}
            className={tab === t.key ? "active" : ""}
          >
            {t.label}
          </Link>
        ))}
      </div>

      {tab === "approvals" ? (
        <ApprovalsTab status={status} />
      ) : (
        <EscalationTab agent={agent} />
      )}
    </>
  );
}

async function ApprovalsTab({ status: rawStatus }: { status?: string }) {
  const status = STATUSES.includes(rawStatus || "") ? rawStatus! : "pending";

  let approvals: any, agents: any, others: any[];
  try {
    // The other three statuses are fetched too, only for their counts. On a
    // healthy estate the default view (pending) is legitimately empty, and the
    // page then said so in one line and stopped — a filter bar whose four
    // options all look identical, above nothing, with no indication that three
    // of them have rows. Counts on the chips cost three small requests and turn
    // a dead end into a direction.
    const rest = STATUSES.filter((x) => x !== status);
    const [self, agentList, ...restRes] = await Promise.all([
      api(`/api/approvals?status=${status}`),
      safeApi("/api/agents", { agents: [] }),
      ...rest.map((x) => safeApi<any>(`/api/approvals?status=${x}`, { approvals: [] })),
    ]);
    approvals = self;
    agents = agentList;
    others = restRes;
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }

  const counts: Record<string, number> = { [status]: approvals.approvals?.length || 0 };
  STATUSES.filter((x) => x !== status).forEach((x, i) => {
    counts[x] = others[i]?.approvals?.length || 0;
  });
  const answered = counts.approved + counts.denied + counts.expired + counts.used;

  const agentSlug: Record<string, string> = {};
  for (const a of agents.agents || []) agentSlug[a.id] = a.slug;

  return (
    <>
      <div className="chipbar" style={{ marginTop: 4, marginBottom: 4 }} role="group" aria-label="Filter approvals by status">
        <span className="chipbar-label">status:</span>
        {STATUSES.map((s) => (
          <Link
            key={s}
            href={`/app/approvals?status=${s}`}
            className={`chip${status === s ? " active" : ""}`}
            aria-current={status === s ? "true" : undefined}
          >
            {s}
            <span className="chip-n">{counts[s]}</span>
          </Link>
        ))}
      </div>

      {/* The panel is skipped entirely on an empty pending queue: the block
          below already says it, and "No pending approvals." in a box directly
          above "Nothing is waiting on you" is the same sentence twice. */}
      {(approvals.approvals?.length > 0 || status !== "pending") && (
      <div className="panel scroll-x">
        {approvals.approvals?.length ? (
          <table>
            <thead>
              <tr>
                <th className="w-name">agent</th>
                <th className="w-name">tool</th>
                <th className="w-prose">reason</th>
                <th className="w-name">arguments</th>
                <th className="w-when">requested</th>
                <th>
                  expires
                  <InfoTip text="Past this time, an unanswered request is denied automatically and the call is blocked — the default timeout action fails closed rather than leaving a risky call in limbo." />
                </th>
                {status === "pending" && <th></th>}
              </tr>
            </thead>
            <tbody>
              {approvals.approvals.map((a: any) => (
                <tr key={a.id}>
                  <td className="small">
                    {agentSlug[a.agent_id] ? (
                      <AgentLink slug={agentSlug[a.agent_id]} agents={agents.agents || []} />
                    ) : (
                      <span className="muted">unattributed</span>
                    )}
                  </td>
                  <td className="mono small">{a.tool || "—"}</td>
                  <td><ReasonCell reason={a.reason} /></td>
                  <td className="w-name">
                    <ArgsCell args={a.arguments} />
                  </td>
                  <td className="small muted">{ts(a.requested_at)}</td>
                  <td className="small">{status === "pending" ? <Countdown at={a.expires_at} /> : <span className="small muted">{ts(a.expires_at)}</span>}</td>
                  {status === "pending" && (
                    <td className="small">
                      <div className="review-actions" style={{ flexDirection: "column", gap: 4 }}>
                        <form action={`/api/approvals/${a.id}/approve`} method="POST" className="row" style={{ gap: 4 }}>
                          <input type="text" name="rationale" aria-label="Approval rationale (optional)" placeholder="rationale (optional)" style={{ padding: "3px 6px", borderRadius: 5, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 11.5, width: 130 }} />
                          <button type="submit" className="btn-approve">Approve</button>
                        </form>
                        <form action={`/api/approvals/${a.id}/deny`} method="POST">
                          <button type="submit" className="btn-reject" title="The tool call does not run — the same outcome as a block verdict.">Deny</button>
                        </form>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No {status} approvals.</Empty>
        )}
      </div>
      )}

      {/* An empty pending queue is the healthy state, and it was rendered as one
          sentence in a box on an otherwise blank page — a page that looks broken
          rather than one that looks quiet. It says what it means instead: nothing
          is waiting, here is what would put something here, and here is where the
          answered ones are. */}
      {status === "pending" && !approvals.approvals?.length && (
        <div className="queue-clear">
          <h3>Nothing is waiting on you</h3>
          <p>
            Every governed tool call was either allowed outright or already
            answered. A call arrives here when the capability grant behind it says{" "}
            <span className="mono">--requires-approval</span>, or when a policy rule
            escalates rather than blocks — most often an irreversible tool called
            with arguments that came from something untrusted.
          </p>
          <p className="qc-links">
            {answered > 0 && (
              <>
                <Link href="/app/approvals?status=approved">
                  {answered} already answered
                </Link>
                {" · "}
              </>
            )}
            <Link href="/app/agents">What each agent may call</Link>
            {" · "}
            <Link href="/app/policies">Which rules escalate</Link>
          </p>
        </div>
      )}
    </>
  );
}

/**
 * P11 — 31.1% of all catalogued failures, and the one control whose failure is
 * invisible from inside the system. A conversation where the agent kept going
 * instead of handing off looks entirely ordinary in the telemetry.
 */
async function EscalationTab({ agent }: { agent?: string }) {
  const agentQs = agent ? `?agent=${encodeURIComponent(agent)}` : "";
  let report: any, missed: any, handoffs: any, agents: any, policy: any;
  try {
    [report, missed, handoffs, agents, policy] = await Promise.all([
      api(`/api/escalation/report${agentQs}`),
      api(`/api/escalation/missed${agentQs}`),
      api(`/api/escalation/handoffs${agentQs}`),
      safeApi("/api/agents", { agents: [] }),
      safeApi("/api/escalation/policy", null),
    ]);
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }

  const rate = report.missed_rate ?? 0;
  const breaching = rate > 0.05;

  return (
    <>
      <p className="small muted" style={{ marginTop: 4, marginBottom: 12 }}>
        Conversations that met an escalation condition and never got a human.{" "}
        <InfoTip text="Click any conversation to see the transcript and which turn triggered it." />
      </p>

      <form action="/app/approvals" method="GET" className="chipbar" style={{ marginBottom: 4 }}>
        <input type="hidden" name="tab" value="escalation" />
        <span className="chipbar-label">agent:</span>
        <select
          name="agent"
          defaultValue={agent ?? ""}
          style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 12, fontFamily: "inherit" }}
        >
          <option value="">all agents</option>
          {(agents.agents || []).map((a: any) => (
            <option key={a.slug} value={a.slug}>{a.slug}</option>
          ))}
        </select>
        <button type="submit" className="chip" style={{ cursor: "pointer" }}>filter</button>
        {agent && (
          <Link href="/app/approvals?tab=escalation" className="chip">clear agent ×</Link>
        )}
      </form>

      {/* Five tiles, three of them zero and wearing a green border to say so,
          above an empty "Missed escalations" section, above the hand-off queue —
          which is the only thing on this tab that needs a person, and it started
          610px down the page. The counts are a strip, the queue comes first, and
          the after-the-fact report follows it. */}
      <InventoryStrip
        items={[
          {
            n: `${(rate * 100).toFixed(1)}%`,
            label: "missed-escalation rate",
            href: "/app/approvals?tab=escalation",
            ...(breaching ? { tone: "bad" as const } : {}),
          },
          {
            n: report.qualified_for_escalation,
            label: "conversations that qualified",
            href: "/app/approvals?tab=escalation",
          },
          {
            n: report.sla_breached,
            label: "hand-offs past SLA",
            href: "#handoffs",
            ...(report.sla_breached ? { tone: "bad" as const } : {}),
          },
          {
            n: report.incomplete_handoffs,
            label: "hand-offs missing context",
            href: "#handoffs",
            ...(report.incomplete_handoffs ? { tone: "warn" as const } : {}),
          },
          {
            n: report.false_resolutions,
            label: "false resolutions",
            href: "#missed",
            ...(report.false_resolutions ? { tone: "warn" as const } : {}),
          },
        ]}
      />

      <h2 id="handoffs">Hand-off queue</h2>
      <p className="sub">
        Each row needs a person.{" "}
        <InfoTip text="'Completeness' scores whether the hand-off carries enough for a human to act without re-interviewing the user: the original request, a summary, what was already tried, why it was blocked, and a customer reference. Missing any of these is its own failure — the hand-off happened and was still unusable." />
      </p>
      <div className="panel">
        {handoffs.handoffs?.length ? (
          <table>
            <thead>
              <tr>
                <th>conversation</th>
                <th>agent</th>
                <th>status</th>
                <th>owner</th>
                <th>context</th>
                <th>due</th>
                <th>reason</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {handoffs.handoffs.map((h: any) => (
                <tr key={h.id}>
                  <td className="small">
                    <Link href={`/app/escalation/conversations/${encodeURIComponent(h.session_id)}`}>
                      {h.summary || h.reason || "Conversation escalated"}
                    </Link>
                    <div className="mono small muted">{h.session_id}</div>
                    {h.session_id?.startsWith("seed-") && (
                      <div>
                        <span
                          className="tag"
                          title="Created by `agentfox seed` for demo purposes — not a real conversation."
                        >
                          sample data
                        </span>
                      </div>
                    )}
                    {h.trace_id && (
                      <div>
                        <Link href={`/app/traces/${h.trace_id}`} className="small">
                          trace
                        </Link>
                      </div>
                    )}
                  </td>
                  <td className="small">
                    {h.agent_slug ? (
                      <AgentLink slug={h.agent_slug} agents={agents.agents || []} />
                    ) : (
                      <span className="muted">unattributed</span>
                    )}
                  </td>
                  <td>
                    <span className={`tag ${h.status === "breached" ? "bad" : h.status === "resolved" ? "ok" : ""}`}>
                      {h.status}
                    </span>
                    {h.detected_retroactively && <span className="tag warn">retroactive</span>}
                  </td>
                  <td>{h.owner_role}</td>
                  <td>
                    <span className={h.completeness.complete ? "tag ok" : "tag warn"}>
                      {Math.round(h.completeness.score * 100)}%
                    </span>
                    {!h.completeness.complete && (
                      <span className="small muted"> missing {h.completeness.missing.join(", ")}</span>
                    )}
                  </td>
                  <td className="small muted">{ts(h.due_at)}</td>
                  <td className="small">{h.reason?.slice(0, 80)}</td>
                  <td className="small">
                    {h.status === "pending" ? (
                      <form action="/api/escalation/handoffs/acknowledge" method="POST">
                        <input type="hidden" name="id" value={h.id} />
                        <button type="submit" className="chip" style={{ cursor: "pointer" }}>acknowledge</button>
                      </form>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No hand-offs raised.</Empty>
        )}
      </div>

      <h2 id="missed">Missed escalations</h2>
      <p className="sub">
        Detected after the fact.{" "}
        <InfoTip text="At runtime there is nothing to see — the failure is the absence of an event." />
      </p>
      <div className="panel">
        {missed.missed?.length ? (
          <table>
            <thead>
              <tr>
                <th>conversation</th>
                <th>agent</th>
                <th>turns</th>
                <th>qualified at</th>
                <th>why a human was needed</th>
              </tr>
            </thead>
            <tbody>
              {missed.missed.map((m: any) => (
                <tr key={m.session_id}>
                  <td className="mono small">
                    <Link href={`/app/escalation/conversations/${encodeURIComponent(m.session_id)}`}>
                      {m.session_id}
                    </Link>
                  </td>
                  <td className="small">
                    {m.agent_slug ? (
                      <AgentLink slug={m.agent_slug} agents={agents.agents || []} />
                    ) : (
                      <span className="muted">unattributed</span>
                    )}
                  </td>
                  <td>{m.turns}</td>
                  <td>turn {m.first_qualifying_turn}</td>
                  <td className="wrap" style={{ maxWidth: 260 }}>
                    {m.triggers.slice(0, 2).map((t: any, i: number) => (
                      <div key={i} className="small">
                        <Severity value={t.severity} /> {t.detail}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>
            None in this window. Either escalation is working, or nothing has been
            recorded yet — check <a href="/app/start">Start here</a>.
          </Empty>
        )}
      </div>

      {/* The policy editor is configuration: a role, an SLA, a mode and a blob
          of JSON conditions. It is not something anyone reads on the way to
          clearing a queue, so it stops sitting under one. */}
      <details className="rt-more" style={{ marginTop: 26 }}>
        <summary>Escalation policy — what qualifies a conversation for a hand-off</summary>
        <h2>
          Escalation policy
          <InfoTip text="What actually qualifies a conversation for a hand-off — org-wide by default. Agent-scoped overrides exist in the API (?agent=slug) but aren't exposed here yet; this edits the default every agent inherits." />
        </h2>
        <p className="sub">
          Every condition is a signal, not a guarantee.{" "}
          <InfoTip text="That is why this pillar ships observe-first. Fields not present in the JSON fall back to the platform default shown as a placeholder." />
        </p>
        <form action="/api/escalation/policy" method="POST" className="panel body stack">
          <div className="field-grid">
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Owner role</label>
              <input
                type="text"
                name="owner_role"
                defaultValue={policy?.owner_role || "support"}
                style={{ width: "100%", padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>SLA (minutes)</label>
              <input
                type="number"
                name="sla_minutes"
                min={1}
                max={10080}
                defaultValue={policy?.sla_minutes ?? 60}
                style={{ width: "100%", padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Mode</label>
              <select
                name="mode"
                defaultValue={policy?.mode || "observe"}
                style={{ width: "100%", padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              >
                <option value="observe">observe</option>
                <option value="enforce">enforce</option>
              </select>
            </div>
          </div>
          <div>
            <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
              Conditions (JSON — explicit_request, repeated_failure, repeated_abstention,
              turn_depth, sentiment_below, regulated_topics, confidence_below)
            </label>
            <textarea
              name="conditions"
              defaultValue={JSON.stringify(policy?.conditions || policy?.defaults || {}, null, 2)}
              spellCheck={false}
              rows={9}
              style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 12.5, lineHeight: 1.5, padding: 10, borderRadius: 7, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", resize: "vertical" }}
            />
          </div>
          <div>
            <button type="submit" className="btn-primary">Save escalation policy</button>
          </div>
        </form>
      </details>

    </>
  );
}
