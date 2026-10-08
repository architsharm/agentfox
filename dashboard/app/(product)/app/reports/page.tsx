import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { BarList, Card, Empty, Grid, Header, Kpi, Pill, Tabs, ago, href, num, pctOf } from "@/components/kit";
import { REPORTS_TABS } from "@/components/product/AreaTabs";
import { PrintButton } from "@/components/product/PrintButton";

export const metadata: Metadata = appPageMetadata("Reports", "Evidence that your agents are under control.");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

const FRAMEWORK_NAMES: Record<string, string> = {
  "eu-ai-act": "EU AI Act",
  "nist-ai-rmf": "NIST AI RMF",
  "iso-42001": "ISO/IEC 42001",
  "soc2": "SOC 2",
  "owasp-llm": "OWASP LLM Top 10",
  "gdpr": "GDPR",
  "dora": "DORA",
};

export default async function Reports({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const tab = sp.tab === "evidence" ? "evidence" : sp.tab === "audit" ? "audit" : "summary";
  return (
    <>
      <Header title="Reports" actions={tab === "summary" ? <PrintButton /> : undefined} />
      <Tabs items={REPORTS_TABS} active={tab} />
      {sp.review_error && <div className="error">{sp.review_error}</div>}
      {sp.review_notice && <div className="note-panel">{sp.review_notice}</div>}
      {tab === "summary" && <Summary />}
      {tab === "evidence" && <Evidence />}
      {tab === "audit" && <Audit />}
    </>
  );
}

async function Summary() {
  const [board, usage] = await Promise.all([
    safeApi<any>("/api/board", null),
    safeApi<any>("/api/metrics/summary?range=30d", null),
  ]);
  if (!board) return <Card><Empty>Summary unavailable.</Empty></Card>;
  const inv = board.inventory || {};
  const findings = board.open_findings || {};
  const posture = Object.values(board.control_posture || {}) as any[];
  const t = usage?.totals || { requests: 0, held: 0, blocked: 0 };
  const best = posture.length ? Math.round((posture.reduce((n, p) => n + (p.effectiveness || 0), 0) / posture.length) * 100) : 0;

  return (
    <>
      <Grid cols={4}>
        <Kpi label="Agents" value={num(inv.agents || 0)} href="/app/agents" hint="Registered and unregistered." />
        <Kpi label="High-risk agents" value={num((board.high_risk_agents || []).length)} href="/app/agents" />
        <Kpi label="Open issues" value={num(findings.total || 0)} tone={findings.by_severity?.critical ? "bad" : undefined} href="/app/findings" />
        <Kpi label="Requests stopped (30d)" value={pctOf(t.held + t.blocked, t.requests)} hint={`${num(t.held + t.blocked)} of ${num(t.requests)} requests held or blocked.`} />
      </Grid>
      <Card title="Frameworks" hint="Share of controls working, computed from live traffic. Mappings are drafts pending review." action={<span>{best}% average</span>} flush>
        <table className="k-table">
          <tbody>
            {posture.map((p) => (
              <tr key={p.framework}>
                <td>
                  <Link className="k-name" href={`/app/compliance/frameworks/${encodeURIComponent(p.framework)}`}>
                    {FRAMEWORK_NAMES[p.framework] || p.framework}
                  </Link>
                </td>
                <td style={{ width: "40%" }}>
                  <span className="k-stack">
                    <span className="k-seg-solid" style={{ width: `${Math.round((p.effectiveness || 0) * 100)}%`, opacity: 0.7 }} />
                  </span>
                </td>
                <td className="num tight">{Math.round((p.effectiveness || 0) * 100)}%</td>
                <td className="tight">
                  {p.failing_controls?.length ? <Pill tone="bad">{p.failing_controls.length} failing</Pill> : <Pill tone="ok">None failing</Pill>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Grid cols={2}>
        <Card title="Open issues by severity">
          <BarList
            rows={["critical", "high", "medium", "low"]
              .filter((s) => findings.by_severity?.[s])
              .map((s) => ({ key: s, label: s[0].toUpperCase() + s.slice(1), value: findings.by_severity[s], href: `/app/findings?severity=${s}` }))}
            empty="No open issues"
          />
        </Card>
        <Card title="Agents by risk">
          <BarList
            rows={Object.entries(board.agents_by_risk_class || {}).map(([k, v]) => ({ key: k, label: k[0].toUpperCase() + k.slice(1), value: v as number }))}
            empty="No agents"
          />
        </Card>
      </Grid>
    </>
  );
}

async function Evidence() {
  const [packages, agents] = await Promise.all([
    safeApi<any>("/api/evidence", { packages: [] }),
    safeApi<any>("/api/agents", { agents: [] }),
  ]);
  return (
    <>
      <Card title="New evidence pack" hint="A signed bundle of decisions, approvals, findings and control status for an auditor.">
        <form action="/api/evidence" method="POST" className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
          <select className="k-select" name="agents" defaultValue="" aria-label="Agent">
            <option value="">All agents</option>
            {(agents.agents || []).map((a: any) => (
              <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>
            ))}
          </select>
          <input className="k-input" type="date" name="period_from" aria-label="From" />
          <input className="k-input" type="date" name="period_to" aria-label="To" />
          <button type="submit" className="k-btn-primary">Build</button>
        </form>
      </Card>
      <Card title="Packs" flush>
        {packages.packages?.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Scope</th>
                <th className="num">Decisions</th>
                <th className="num">Approvals</th>
                <th className="tight">Integrity</th>
                <th className="tight">Built</th>
                <th className="tight" />
              </tr>
            </thead>
            <tbody>
              {packages.packages.map((p: any) => (
                <tr key={p.id}>
                  <td>
                    {p.scope?.agents?.length ? p.scope.agents.join(", ") : "All agents"}
                    <span className="sub">
                      {p.scope?.period_from ? `${String(p.scope.period_from).slice(0, 10)} – ${String(p.scope.period_to || "").slice(0, 10)}` : "All time"}
                      {" · "}by {p.requested_by}
                    </span>
                  </td>
                  <td className="num">{num(p.counts?.decisions || 0)}</td>
                  <td className="num">{num(p.counts?.approvals || 0)}</td>
                  <td className="tight">{p.chain_valid ? <Pill tone="ok">Verified</Pill> : <Pill tone="bad">Broken</Pill>}</td>
                  <td className="tight muted">{ago(p.built_at)}</td>
                  <td className="tight">
                    <a className="k-btn" href={`/api/evidence/${p.id}/download`}>Download</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No evidence packs yet.</Empty>
        )}
      </Card>
    </>
  );
}

async function Audit() {
  const data = await safeApi<any>("/api/audit/entries?limit=100", { stats: {}, entries: [] });
  const stats = data.stats || {};
  return (
    <>
      <Grid cols={3}>
        <Kpi label="Recorded events" value={num(stats.entries || 0)} />
        <Kpi label="Signed checkpoints" value={num(stats.checkpoints || 0)} />
        <Card>
          <form action="/api/audit/verify" method="POST" className="k-pills" style={{ gap: 10, height: "100%" }}>
            <span className="k-muted" style={{ fontSize: "var(--t-micro)" }}>Check nothing was changed or removed.</span>
            <button type="submit" className="k-btn-primary">Verify log</button>
          </form>
        </Card>
      </Grid>
      <Card title="Latest events" flush>
        {data.entries?.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th className="tight">#</th>
                <th className="tight">When</th>
                <th>Who</th>
                <th>What</th>
                <th>Subject</th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((e: any) => (
                <tr key={e.seq}>
                  <td className="tight muted">{e.seq}</td>
                  <td className="tight muted">{ago(e.occurred_at)}</td>
                  <td>{e.actor_id}</td>
                  <td>{String(e.action).replace(/[._]/g, " ")}</td>
                  <td className="muted">
                    {e.payload?.trace_id ? <Link href={`/app/traces/${e.payload.trace_id}`}>{e.subject_type}</Link> : e.subject_type}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No events.</Empty>
        )}
      </Card>
    </>
  );
}
