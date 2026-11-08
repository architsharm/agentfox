import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { BarList, Card, Empty, Grid, Header, Kpi, Pill, Tabs, ago, href, num, pctOf } from "@/components/kit";
import { AreaTabs, REPORTS_TABS } from "@/components/product/AreaTabs";
import { EnterpriseOnly } from "@/components/product/EnterpriseOnly";
import { hasFeature } from "@/lib/product/edition";
import { controlShare } from "@/lib/product/posture";
import { PrintButton } from "@/components/product/PrintButton";
import { NoticeToast } from "@/components/product/NoticeToast";

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
      <AreaTabs tabs={REPORTS_TABS} active={tab} />
      <NoticeToast notice={sp.review_notice} error={sp.review_error} />
      {tab === "summary" && <Summary />}
      {tab === "evidence" && ((await hasFeature("evidence")) ? <Evidence /> : <EnterpriseOnly feature="evidence" />)}
      {tab === "audit" && <Audit />}
    </>
  );
}

async function Summary() {
  const compliance = await hasFeature("compliance");
  const [overview, board, usage] = await Promise.all([
    safeApi<any>("/api/overview", null),
    // Control status by framework is AgentFox Enterprise.
    compliance ? safeApi<any>("/api/board", null) : Promise.resolve(null),
    safeApi<any>("/api/metrics/summary?range=30d", null),
  ]);
  if (!overview) return <Card><Empty>Summary unavailable.</Empty></Card>;
  const inv = overview.inventory || {};
  const findings = overview.open_findings || {};
  const posture = Object.values(board?.control_posture || {}) as any[];
  const t = usage?.totals || { requests: 0, held: 0, blocked: 0 };
  // Working out of every control that applies, not out of the ones measured: "8 of 8
  // measured" read as 100% with 29 controls not set up at all. One helper, shared with
  // Reports → Compliance, so the two tabs say the same number.
  const inScope = (p: any) => controlShare(p).applies;
  const working = (p: any) => controlShare(p).working;
  const share = (p: any) => controlShare(p).share ?? 0;
  // The workspace's own figure (every control once), not an average of framework
  // rows, which double-counted every control mapped to more than one framework.
  const overall = controlShare(board?.overall_posture);
  const computedAt = posture.map((p) => p.computed_at).filter(Boolean).sort()[0];
  // Every framework row the same: say why rather than look like a copy-paste bug.
  const allSame =
    posture.length > 1 && posture.every((p) => working(p) === working(posture[0]) && inScope(p) === inScope(posture[0]));
  // The same counts the "Agents by risk" panel below draws from.
  const byClass: Record<string, number> = overview.agents_by_risk_class || {};
  const agentsTotal = Object.values(byClass).reduce((n, v) => n + (v || 0), 0);
  const highRisk = (byClass.high || 0) + (byClass.prohibited || 0);

  return (
    <>
      <Grid cols={4}>
        <Kpi label="Agents" value={num(agentsTotal || inv.agents || 0)} href="/app/projects" hint="Every agent not retired, registered or found by a scan. The risk panel below counts the same agents." />
        <Kpi label="High-risk agents" value={num(highRisk)} href="/app/projects" hint="Risk tier high or prohibited, as in Agents by risk below." />
        <Kpi label="Open issues" value={num(findings.total || 0)} tone={findings.by_severity?.critical ? "bad" : undefined} href="/app/findings" />
        <Kpi label="Requests held or blocked (30d)" value={pctOf(t.held + t.blocked, t.requests)} hint={`${num(t.held + t.blocked)} of ${num(t.requests)} requests. Traffic, not controls: Frameworks below is a different measure.`} />
      </Grid>
      {compliance && (
        <Card
          title="Frameworks"
          hint={`Controls working, out of every control that applies, computed from live traffic. Mappings are drafts pending review.${allSame ? " Every framework below maps the same controls, so their rows match." : ""}`}
          action={
            <span>
              {overall.share == null ? "—" : `${Math.round(overall.share * 100)}%`} of controls working ({overall.working} of {overall.applies})
              {computedAt ? <span className="k-muted"> · updated {ago(computedAt)} · </span> : " · "}
              <Link href="/app/compliance">Recompute</Link>
            </span>
          }
          flush
        >
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
                      <span className="k-seg-solid" style={{ width: `${Math.round(share(p) * 100)}%`, opacity: 0.7 }} />
                    </span>
                  </td>
                  <td className="num tight">
                    {working(p)} of {inScope(p)} working
                  </td>
                  <td className="tight">
                    {p.failing_controls?.length ? (
                      <Pill tone="bad">{p.failing_controls.length} failing</Pill>
                    ) : p.counts?.not_implemented ? (
                      <Pill tone="outline">{p.counts.not_implemented} not set up</Pill>
                    ) : (
                      <Pill tone="ok">All working</Pill>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
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
            rows={Object.entries(overview.agents_by_risk_class || {}).map(([k, v]) => ({ key: k, label: `${k[0].toUpperCase() + k.slice(1)} risk`, value: v as number }))}
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
                    {e.payload?.trace_id ? <Link href={`/app/traces/${e.payload.trace_id}`}>{subjectWords(e.subject_type)}</Link> : subjectWords(e.subject_type)}
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

/** An audit subject as words: "api_token" reads "API token", "retention_run" "Retention run". */
function subjectWords(subject?: string | null): string {
  if (!subject) return "";
  const words = String(subject)
    .replace(/[._]+/g, " ")
    .replace(/\b(api|id|mcp|sso|llm)\b/gi, (w) => w.toUpperCase())
    .trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "";
}
