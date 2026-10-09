import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { Card, Empty, Header, Pill, Tabs, ago, href } from "@/components/kit";
import { Countdown } from "@/components/product/Countdown";
import { EscalationTab } from "@/components/product/approvals/escalation";
import { TRUST } from "@/lib/product/vocab";

export const metadata: Metadata = appPageMetadata("Approvals", "Actions waiting for a person.");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

const HISTORY = ["approved", "denied", "expired", "used"];
const STATUS_TONE: Record<string, "ok" | "bad" | "warn" | "neutral"> = { approved: "ok", used: "ok", denied: "bad", expired: "warn" };

function source(s?: string) {
  return TRUST.find((t) => t.key === s)?.label.replace(/^\+ /, "") || s || "";
}

export default async function Approvals({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const tab = sp.tab === "history" ? "history" : sp.tab === "handoffs" || sp.tab === "escalation" ? "handoffs" : "pending";
  const pending = await safeApi<any>("/api/approvals?status=pending", { approvals: [] });

  return (
    <>
      <Header title="Approvals" />
      <Tabs
        active={tab}
        items={[
          { key: "pending", label: "Waiting", href: "/app/approvals", count: pending.approvals?.length },
          { key: "history", label: "History", href: "/app/approvals?tab=history" },
          { key: "handoffs", label: "Hand-offs", href: "/app/approvals?tab=handoffs" },
        ]}
      />
      {sp.review_error && <div className="error">{sp.review_error}</div>}
      {sp.review_notice && <div className="note-panel">Request {sp.review_notice}.</div>}
      {tab === "pending" && <Pending approvals={pending.approvals || []} />}
      {tab === "history" && <History status={sp.status} />}
      {tab === "handoffs" && <EscalationTab agent={sp.agent} />}
    </>
  );
}

async function Pending({ approvals }: { approvals: any[] }) {
  if (!approvals.length) return <Card><Empty>Nothing is waiting for you.</Empty></Card>;
  const shown = approvals.slice(0, 25);
  const [agents, traces] = await Promise.all([
    safeApi<any>("/api/agents", { agents: [] }),
    Promise.all(shown.map((a) => (a.trace_id ? safeApi<any>(`/api/traces/${a.trace_id}`, null) : Promise.resolve(null)))),
  ]);
  const name: Record<string, any> = Object.fromEntries((agents.agents || []).map((a: any) => [a.id, a]));

  return (
    <div className="k-form">
      {shown.map((a, i) => {
        const agent = name[a.agent_id];
        const decision = (traces[i]?.decisions || []).find((d: any) => d.id === a.decision_id) || traces[i]?.decisions?.[0];
        const origin: Record<string, string> = decision?.taint?.arguments || {};
        return (
          <section key={a.id} className="k-card k-approval">
            <div className="k-card-body">
              <div className="k-approval-main">
                <div>
                  <strong>{agent?.name || "An agent"}</strong> wants to run <span className="k-mono">{a.tool}</span>
                </div>
                <div className="k-pills" style={{ flexWrap: "wrap", gap: 6 }}>
                  {Object.entries(a.arguments || {}).map(([k, v]) => {
                    const from = origin[k];
                    const risky = from && from !== "user" && from !== "none";
                    return (
                      <Pill key={k} tone={risky ? "held" : "neutral"} title={from ? `From ${source(from)}` : undefined}>
                        {k}: {typeof v === "string" ? v : JSON.stringify(v)}
                        {risky ? ` · from ${source(from).toLowerCase()}` : ""}
                      </Pill>
                    );
                  })}
                </div>
                <div className="k-muted" style={{ fontSize: "var(--t-micro)" }}>
                  {String(a.reason || "").split(/(?<=\.)\s/)[0]} · expires <Countdown at={a.expires_at} /> · <span className="k-mono" title="The id the agent quoted to the user">{a.id}</span>
                  {a.trace_id && (
                    <>
                      {" · "}
                      <Link href={`/app/traces/${a.trace_id}`}>Run</Link>
                    </>
                  )}
                </div>
              </div>
              <div className="k-approval-actions">
                <form action={`/api/approvals/${a.id}/deny`} method="POST">
                  <input type="hidden" name="return_to" value="/app/approvals" />
                  <button type="submit" className="k-btn-danger">Deny</button>
                </form>
                <form action={`/api/approvals/${a.id}/approve`} method="POST">
                  <input type="hidden" name="return_to" value="/app/approvals" />
                  <button type="submit" className="k-btn-primary">Approve</button>
                </form>
              </div>
            </div>
          </section>
        );
      })}
      {approvals.length > shown.length && <div className="k-muted">{approvals.length - shown.length} more waiting.</div>}
    </div>
  );
}

async function History({ status }: { status?: string }) {
  const statuses = status && HISTORY.includes(status) ? [status] : HISTORY;
  const [lists, agents] = await Promise.all([
    Promise.all(statuses.map((s) => safeApi<any>(`/api/approvals?status=${s}`, { approvals: [] }))),
    safeApi<any>("/api/agents", { agents: [] }),
  ]);
  const name: Record<string, any> = Object.fromEntries((agents.agents || []).map((a: any) => [a.id, a]));
  const rows = lists.flatMap((l) => l.approvals || []).sort((a, b) => String(b.requested_at).localeCompare(String(a.requested_at)));

  return (
    <>
      <div className="k-toolbar">
        <div className="k-seg" role="group" aria-label="Status">
          <Link href="/app/approvals?tab=history" className={!status ? "active" : ""} scroll={false}>All</Link>
          {HISTORY.map((s) => (
            <Link key={s} href={href("/app/approvals", { tab: "history", status: s })} className={status === s ? "active" : ""} scroll={false}>
              {s[0].toUpperCase() + s.slice(1)}
            </Link>
          ))}
        </div>
      </div>
      <Card flush>
        {rows.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th className="tight">When</th>
                <th>Agent</th>
                <th>Action</th>
                <th className="tight">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="tight muted">{ago(a.requested_at)}</td>
                  <td>{name[a.agent_id]?.name || "—"}</td>
                  <td>
                    {a.trace_id ? <Link className="k-name" href={`/app/traces/${a.trace_id}`}>{a.tool}</Link> : <span className="k-name">{a.tool}</span>}
                    <span className="sub">
                      {Object.entries(a.arguments || {})
                        .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
                        .join(" · ")}
                    </span>
                  </td>
                  <td className="tight"><Pill tone={STATUS_TONE[a.status] || "neutral"}>{a.status}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No decisions yet.</Empty>
        )}
      </Card>
    </>
  );
}
