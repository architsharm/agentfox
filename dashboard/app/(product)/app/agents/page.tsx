import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps, safeApi } from "@/lib/product/api";
import { ApiDown } from "@/components/ui";
import { Card, Dot, Empty, Header, Pill, StackBar, Tabs, ago, href, num, pctOf } from "@/components/kit";
import { Modal } from "@/components/product/Modal";

export const metadata: Metadata = appPageMetadata("Agents", "Every AI agent in this workspace.");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

export default async function Agents({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  let agents: any;
  try {
    agents = await api("/api/agents");
  } catch (e: any) {
    return (
      <>
        <Header title="Agents" />
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }
  const [usage, findings] = await Promise.all([
    safeApi<any>("/api/metrics/breakdown?dim=agent&range=7d", { rows: [] }),
    safeApi<any>("/api/findings?status=open", { findings: [] }),
  ]);

  const all: any[] = agents.agents || [];
  const proposed = all.filter((a) => a.status === "draft");
  const live = all.filter((a) => a.status !== "draft");
  const attention = live.filter((a) => !a.registered || !a.owner_email);
  const tab = sp.tab === "attention" ? "attention" : sp.tab === "proposed" ? "proposed" : "all";
  const rows = tab === "attention" ? attention : live;

  const byAgent: Record<string, any> = Object.fromEntries((usage.rows || []).map((r: any) => [r.key, r]));
  const issues: Record<string, number> = {};
  for (const f of findings.findings || []) if (f.agent_slug) issues[f.agent_slug] = (issues[f.agent_slug] || 0) + 1;
  const max = Math.max(1, ...Object.values(byAgent).map((r: any) => r.requests));

  return (
    <>
      <Header title="Agents" actions={<RegisterAgent />} />
      <Tabs
        active={tab}
        items={[
          { key: "all", label: "All", href: "/app/agents", count: live.length },
          { key: "attention", label: "Needs attention", href: "/app/agents?tab=attention", count: attention.length },
          { key: "proposed", label: "Proposed", href: "/app/agents?tab=proposed", count: proposed.length },
        ]}
      />
      {sp.review_error && <div className="error">{sp.review_error}</div>}

      {tab === "proposed" ? (
        <Card flush>
          {proposed.length ? (
            <ul className="k-list">
              {proposed.map((a) => (
                <li key={a.id}>
                  <div className="k-list-main">
                    <span className="k-name">{a.name || a.slug}</span>
                    <span className="muted">Found by a repo scan{a.framework ? ` · ${a.framework}` : ""}</span>
                  </div>
                  <div className="k-list-end">
                    <form action={`/api/agents/${a.id}/reject`} method="POST">
                      <button type="submit" className="k-btn-ghost">Dismiss</button>
                    </form>
                    <form action={`/api/agents/${a.id}/approve`} method="POST">
                      <button type="submit" className="k-btn-primary">Add agent</button>
                    </form>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty action={<Link href="/app/start?tab=connect" className="k-btn">Scan a repo</Link>}>Nothing proposed.</Empty>
          )}
        </Card>
      ) : (
        <Card flush>
          {rows.length ? (
            <table className="k-table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Owner</th>
                  <th className="tight">Risk</th>
                  <th style={{ width: "18%" }}>Last 7 days</th>
                  <th className="num">Requests</th>
                  <th className="num">Stopped</th>
                  <th className="num">Issues</th>
                  <th className="tight">Last active</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const u = byAgent[a.slug] || { requests: 0, held: 0, blocked: 0 };
                  return (
                    <tr key={a.slug}>
                      <td>
                        <span className="k-pills">
                          <Dot tone={a.control_state && a.control_state !== "active" ? "bad" : a.last_seen_at ? "ok" : "idle"} />
                          <Link className="k-name" href={`/app/agents/${encodeURIComponent(a.slug)}`}>
                            {a.name || a.slug}
                          </Link>
                          {!a.registered && <Pill tone="bad">Unregistered</Pill>}
                        </span>
                        {a.purpose && <span className="sub">{a.purpose}</span>}
                      </td>
                      <td>
                        {a.owner_email ? (
                          <span className="k-muted">{a.owner_email}</span>
                        ) : (
                          <Link href={href(`/app/agents/${encodeURIComponent(a.slug)}`, { tab: "settings" })}>Assign</Link>
                        )}
                      </td>
                      <td className="tight">
                        <Pill tone={a.risk_tier === "high" || a.risk_tier === "prohibited" ? "held" : "neutral"}>{a.risk_tier || "—"}</Pill>
                      </td>
                      <td>
                        <StackBar s={u} total={u.requests} scale={max} />
                      </td>
                      <td className="num">{num(u.requests)}</td>
                      <td className="num">{u.requests ? pctOf(u.held + u.blocked, u.requests) : "—"}</td>
                      <td className="num">
                        {issues[a.slug] ? <Link href={href("/app/findings", { agent: a.slug })}>{issues[a.slug]}</Link> : <span className="k-muted">0</span>}
                      </td>
                      <td className="tight muted">{ago(a.last_seen_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <Empty action={<Link href="/app/start" className="k-btn-primary">Connect an agent</Link>}>
              {tab === "attention" ? "Every agent is registered and owned." : "No agents yet."}
            </Empty>
          )}
        </Card>
      )}
    </>
  );
}

function RegisterAgent() {
  return (
    <Modal trigger="Register agent" triggerClassName="k-btn-primary" title="Register agent">
      <form action="/api/agents" method="POST" className="k-form">
        <div className="k-field">
          <label htmlFor="r-slug">ID</label>
          <input id="r-slug" className="k-input" name="slug" required placeholder="billing-support" />
        </div>
        <div className="k-field">
          <label htmlFor="r-name">Name</label>
          <input id="r-name" className="k-input" name="name" placeholder="Billing Support Agent" />
        </div>
        <div className="k-field">
          <label htmlFor="r-purpose">Purpose</label>
          <input id="r-purpose" className="k-input" name="purpose" placeholder="Answers billing questions" />
        </div>
        <div className="k-field">
          <label htmlFor="r-owner">Owner</label>
          <input id="r-owner" className="k-input" type="email" name="owner_email" placeholder="owner@company.com" />
        </div>
        <div className="k-field">
          <label htmlFor="r-risk">Risk level</label>
          <select id="r-risk" className="k-select" name="risk_tier" defaultValue="limited">
            <option value="minimal">Minimal</option>
            <option value="limited">Limited</option>
            <option value="high">High</option>
            <option value="prohibited">Prohibited</option>
          </select>
        </div>
        <div className="k-field">
          <span />
          <span>
            <button type="submit" className="k-btn-primary">Register</button>
          </span>
        </div>
      </form>
    </Modal>
  );
}
