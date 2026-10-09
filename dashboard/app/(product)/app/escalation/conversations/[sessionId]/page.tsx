import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { ApiError, api, apiErrorProps } from "@/lib/product/api";
import { Header } from "@/components/kit";
import { ApiDown, InfoTip, NotFound, Severity, ts } from "@/components/ui";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Escalated conversation");

export const dynamic = "force-dynamic";

/**
 * The transcript behind one row of the missed-escalation or hand-off table —
 * what the user actually said, turn by turn, and exactly which condition the
 * policy fired (or should have fired) on and where.
 */
export default async function EscalationConversation({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  let data: any;
  try {
    data = await api(`/api/escalation/conversations/${encodeURIComponent(sessionId)}`);
  } catch (e: any) {
    return (
      <>
        <h1>Conversation</h1>
        {e instanceof ApiError && e.status === 404 ? (
          <NotFound
            what="recorded conversation"
            detail={`${sessionId}: no turns were recorded for this session`}
            back={{ href: "/app/approvals?tab=escalation", label: "Escalation" }}
          />
        ) : (
          <ApiDown {...apiErrorProps(e)} />
        )}
      </>
    );
  }

  const assessment = data.assessment || {};
  const triggersByTurn = new Map<number, any[]>();
  for (const t of assessment.triggers || []) {
    if (!triggersByTurn.has(t.turn_index)) triggersByTurn.set(t.turn_index, []);
    triggersByTurn.get(t.turn_index)!.push(t);
  }

  return (
    <>
      <Header back={{ href: "/app/approvals?tab=handoffs", label: "Hand-offs" }} title={data.handoff?.summary || data.handoff?.reason || "Conversation"} />
      <p className="mono small muted" style={{ marginTop: -8 }}>{sessionId}</p>
      <p className="sub">
        Every turn of this conversation, replayed against the escalation policy, so
        you can see exactly what the user said and which condition did or didn&rsquo;t
        fire, rather than trusting a summary of it.
        {data.agent_slug && (
          <>
            {" "}Agent: <Link href={`/app/agents/${data.agent_slug}`}>{data.agent_name || data.agent_slug}</Link>.
          </>
        )}
      </p>

      <div className="cards">
        <div className={`card ${assessment.missed ? "bad" : assessment.should_escalate ? "ok" : ""}`}>
          <div className="n">{assessment.should_escalate ? "yes" : "no"}</div>
          <div className="l">qualified for escalation</div>
        </div>
        <div className={`card ${assessment.escalated ? "ok" : assessment.missed ? "bad" : ""}`}>
          <div className="n">{assessment.escalated ? "yes" : "no"}</div>
          <div className="l">actually escalated</div>
        </div>
        <div className="card">
          <div className="n">{assessment.turns ?? data.turns?.length ?? 0}</div>
          <div className="l">turns</div>
        </div>
        <div className={`card ${data.turn_depth?.degrading ? "warn" : ""}`}>
          <div className="n">{data.turn_depth?.depth ?? "—"}</div>
          <div className="l">
            depth vs {data.turn_depth?.limit ?? "?"} limit
            <InfoTip text="Once a conversation runs past half the configured turn-depth limit, a rising rate of abstention among those later turns is treated as quality degradation: not evaluated behavior, drifting past the point anyone checked it." />
          </div>
        </div>
      </div>

      {assessment.missed && (
        <div className="note-panel" style={{ borderLeftColor: "var(--bad)" }}>
          <strong>This conversation met an escalation condition and no hand-off was raised.</strong>{" "}
          That is the failure this control exists to catch: the telemetry looks
          ordinary, so nothing else would have surfaced it.
        </div>
      )}

      {data.handoff && (
        <div className="note-panel">
          A hand-off <strong>was</strong> raised for this conversation
          {data.handoff.detected_retroactively ? " (detected retroactively)" : ""}. Status{" "}
          <span className={`tag ${data.handoff.status === "breached" ? "bad" : data.handoff.status === "resolved" ? "ok" : ""}`}>
            {data.handoff.status}
          </span>
          , owner <strong>{data.handoff.owner_role}</strong>, due {ts(data.handoff.due_at)}.
          {!data.handoff.completeness?.complete && (
            <> Missing context: {data.handoff.completeness?.missing?.join(", ")}.</>
          )}
        </div>
      )}

      <h2>Transcript</h2>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>user</th>
              <th>agent</th>
              <th>
                triggers on this turn
                <InfoTip text="What the escalation policy detected on this specific turn, the same conditions replayed by the missed-escalation scan." />
              </th>
            </tr>
          </thead>
          <tbody>
            {(data.turns || []).map((t: any) => {
              const triggers = triggersByTurn.get(t.index) || [];
              return (
                <tr key={t.index}>
                  <td className="small muted">
                    {t.index}
                    {t.trace_id && (
                      <div>
                        <Link href={`/app/traces/${t.trace_id}`} className="small">
                          trace
                        </Link>
                      </div>
                    )}
                  </td>
                  <td className="small" style={{ maxWidth: 320 }}>
                    {t.user_text || <span className="muted">—</span>}
                  </td>
                  <td className="small" style={{ maxWidth: 320 }}>
                    {t.agent_text || <span className="muted">—</span>}
                    {t.claims_resolution && <span className="tag"> claims resolved</span>}
                    {t.escalated && <span className="tag ok"> escalated here</span>}
                  </td>
                  <td className="small wrap" style={{ maxWidth: 260 }}>
                    {triggers.length === 0 ? (
                      <span className="muted">—</span>
                    ) : (
                      triggers.map((trig: any, i: number) => (
                        <div key={i}>
                          <Severity value={trig.severity} /> <span className="mono small">{trig.condition}</span>{" "}
                          {trig.detail}
                        </div>
                      ))
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
