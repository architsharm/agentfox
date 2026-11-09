import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps, safeApi } from "@/lib/product/api";
import { activeRange } from "@/lib/product/range";
import { RANGE_WORDS } from "@/lib/product/vocab";
import { ApiDown } from "@/components/ui";
import { Card, Dot, Empty, Header, Pill, StackBar, Tabs, ago, href, num, pctOf } from "@/components/kit";
import { Modal } from "@/components/product/Modal";
import { byRepo, groupProposed, isAdded, isProposed, memberRelation, noAgents, proposedSource, searchProposed } from "@/lib/product/proposedSystems";
import { ProposedBulk } from "@/components/product/ProposedBulk";
import { NoticeToast } from "@/components/product/NoticeToast";

export const metadata: Metadata = appPageMetadata("Agents", "Every agent in this workspace.");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

export default async function Projects({ searchParams }: { searchParams: Promise<SP> }) {
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
  const { range } = await activeRange();
  const [usage, findings] = await Promise.all([
    safeApi<any>(`/api/metrics/breakdown?dim=agent&range=${range}`, { rows: [] }),
    safeApi<any>("/api/findings?status=open", { findings: [] }),
  ]);

  const all: any[] = agents.agents || [];
  const proposed = all.filter(isProposed);
  // A long list (a monorepo, a scan of many apps): searched, and grouped by the
  // repository each came from, each group with Add all / Dismiss all.
  const q = (sp.q || "").trim();
  const shownProposed = searchProposed(proposed, q);
  const repos = byRepo(shownProposed);
  const live = all.filter(isAdded);
  // Why each one needs attention, said on its row.
  const reasons = (a: any) => [!a.registered && "Not registered: seen in traffic, never added", !a.owner_email && "No owner"].filter(Boolean) as string[];
  const attention = live.filter((a) => reasons(a).length > 0);
  const tab = sp.tab === "attention" ? "attention" : sp.tab === "proposed" ? "proposed" : "all";
  const rows = tab === "attention" ? attention : live;

  const byAgent: Record<string, any> = Object.fromEntries((usage.rows || []).map((r: any) => [r.key, r]));
  const issues: Record<string, number> = {};
  for (const f of findings.findings || []) if (f.agent_slug) issues[f.agent_slug] = (issues[f.agent_slug] || 0) + 1;
  const max = Math.max(1, ...Object.values(byAgent).map((r: any) => r.requests));

  return (
    <>
      <Header title="Agents" actions={<NewAgent />} />
      <Tabs
        active={tab}
        items={[
          { key: "all", label: "All", href: "/app/projects", count: live.length },
          { key: "attention", label: "Needs attention", href: "/app/projects?tab=attention", count: attention.length },
          { key: "proposed", label: "Proposed", href: "/app/projects?tab=proposed", count: proposed.length },
        ]}
      />
      <NoticeToast error={sp.review_error} />

      {tab === "proposed" ? (
        <>
          {proposed.length > 8 && (
            <form method="GET" action="/app/projects" className="gs-row" role="search" style={{ margin: "12px 0" }}>
              <input type="hidden" name="tab" value="proposed" />
              <input className="k-input" type="search" name="q" defaultValue={q} placeholder="Search by name, repository or framework" aria-label="Search proposed agents" />
              <button type="submit" className="k-btn">Search</button>
              {q && <Link href="/app/projects?tab=proposed">Clear</Link>}
            </form>
          )}
          {proposed.length > 1 && (
            <div className="gs-row" style={{ justifyContent: "space-between", margin: "8px 0" }}>
              <span className="k-muted">
                {q ? `${shownProposed.length} of ${proposed.length} match` : `${proposed.length} waiting to be added`}
              </span>
              <ProposedBulk ids={shownProposed.map((a) => a.id)} label={q ? "the matching agents" : "every proposed agent"} />
            </div>
          )}
          {proposed.length === 0 ? (
            <Card>
              <Empty action={<Link href="/app/settings?tab=connect" className="k-btn">Scan a repo</Link>}>Nothing proposed.</Empty>
            </Card>
          ) : shownProposed.length === 0 ? (
            <Card>
              <Empty>No proposed agent matches “{q}”.</Empty>
            </Card>
          ) : (
            repos.map(({ repo, agents: inRepo }) => (
              <Card
                key={repo ?? "(none)"}
                title={repos.length > 1 || repo ? `${repo ?? "Not from a repository"} · ${inRepo.length} ${inRepo.length === 1 ? "agent" : "agents"}` : undefined}
                action={repos.length > 1 && inRepo.length > 1 ? <ProposedBulk ids={inRepo.map((a) => a.id)} project={q ? null : repo} label={repo ?? "these agents"} /> : undefined}
                flush
              >
                <ProposedList agents={inRepo} />
              </Card>
            ))
          )}
        </>
      ) : (
        <Card flush>
          {rows.length ? (
            <table className="k-table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Owner</th>
                  <th className="tight">Risk</th>
                  <th style={{ width: "18%" }}>Last {RANGE_WORDS[range]}</th>
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
                          <Link className="k-name" href={`/app/projects/${encodeURIComponent(a.slug)}`}>
                            {a.name || a.slug}
                          </Link>
                          {!a.registered && <Pill tone="bad">Unregistered</Pill>}
                        </span>
                        {tab === "attention" ? (
                          <span className="sub">{reasons(a).join(" · ")}</span>
                        ) : (
                          a.purpose && <span className="sub">{a.purpose}</span>
                        )}
                      </td>
                      <td>
                        {a.owner_email ? (
                          <span className="k-muted">{a.owner_email}</span>
                        ) : (
                          <Link href={href(`/app/projects/${encodeURIComponent(a.slug)}`, { view: "settings" })}>Assign</Link>
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
            tab === "attention" ? (
              <Empty>Every agent is registered and owned.</Empty>
            ) : (
              <Empty action={<Link href={noAgents(proposed.length).href} className="k-btn-primary">{noAgents(proposed.length).action}</Link>}>
                {noAgents(proposed.length).text}
              </Empty>
            )
          )}
        </Card>
      )}
    </>
  );
}

/** One repository's proposals: a multi-agent system together, its members indented under it. */
function ProposedList({ agents }: { agents: any[] }) {
  return (
    <ul className="k-list">
      {groupProposed(agents).flatMap((g) => {
        const system = g.members.length > 1;
        const rows = g.members.map(({ agent: a, depth, relation }) => (
          <li key={a.id} style={depth ? { paddingLeft: `${16 + depth * 24}px` } : undefined}>
            <div className="k-list-main">
              <span className="k-name">{a.name || a.slug}</span>
              <span className="muted">
                {depth ? memberRelation(relation) : proposedSource(a)}
                {a.framework ? ` · ${a.framework}` : ""}
                {(a.declared_tools || []).length ? ` · ${(a.declared_tools || []).length} tool${(a.declared_tools || []).length === 1 ? "" : "s"}` : ""}
              </span>
            </div>
            <div className="k-list-end">
              <form action={`/api/agents/${a.id}/reject`} method="POST">
                <button type="submit" className="k-btn-ghost">Dismiss</button>
              </form>
              <form action={`/api/agents/${a.id}/approve`} method="POST">
                <button type="submit" className={system ? "k-btn" : "k-btn-primary"}>Add agent</button>
              </form>
            </div>
          </li>
        ));
        if (!system) return rows;
        return [
          <li key={`system:${g.root.id}`}>
            <div className="k-list-main">
              <span className="k-name">Multi-agent system · {g.members.length} agents</span>
              <span className="muted">The agents its code hands work to are listed under it</span>
            </div>
            <div className="k-list-end">
              <form action={`/api/agents/${g.root.id}/approve-system`} method="POST">
                <button type="submit" className="k-btn-primary">Add all {g.members.length}</button>
              </form>
            </div>
          </li>,
          ...rows,
        ];
      })}
    </ul>
  );
}

function NewAgent() {
  return (
    <Modal trigger="New agent" triggerClassName="k-btn-primary" title="New agent">
      <form action="/api/agents" method="POST" className="k-form">
        <div className="k-field">
          <label htmlFor="r-slug">ID</label>
          <input id="r-slug" className="k-input" name="slug" required placeholder="billing-support" />
        </div>
        <div className="k-field">
          <label htmlFor="r-name">Name</label>
          <input id="r-name" className="k-input" name="name" placeholder="Billing support" />
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
