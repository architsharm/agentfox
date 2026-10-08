/**
 * The conversation hand-off queue, missed escalations and the escalation policy
 * form, as they were before the redesign. Rendered under Approvals → Hand-offs.
 */
import Link from "next/link";
import { api, safeApi, apiErrorProps } from "@/lib/product/api";
import { AgentLink, ApiDown, ArgsCell, Empty, InfoTip, InventoryStrip, Severity, ts } from "@/components/ui";
import { PageHeader } from "@/components/product/PageHeader";
import { Countdown } from "@/components/product/Countdown";


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

export async function EscalationTab({ agent }: { agent?: string }) {
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
                          title="Created by `agentfox admin seed` for demo purposes — not a real conversation."
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
            recorded yet — check <a href="/app/start">Get started</a>.
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
