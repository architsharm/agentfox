import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { Card, Empty, Grid, Header, Kpi, Pill, Tabs, ago, href, num } from "@/components/kit";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";
import { TryIt } from "@/components/product/test/TryIt";
import { publicApiBase } from "@/lib/env";

export const metadata: Metadata = appPageMetadata("Test", "Check rules and agents before they meet real traffic.");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

const TABS = [
  { key: "try", label: "Try it" },
  { key: "attacks", label: "Attack tests" },
  { key: "suites", label: "Test suites" },
  { key: "reliability", label: "Reliability" },
  { key: "ci", label: "CI" },
];

export default async function Test({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const tab = TABS.some((t) => t.key === sp.tab) ? sp.tab! : "try";
  const agents = await safeApi<any>("/api/agents", { agents: [] });
  const live = (agents.agents || []).filter((a: any) => a.status !== "draft");

  return (
    <>
      <Header title="Test" />
      <Tabs items={TABS.map((t) => ({ ...t, href: href("/app/test", { tab: t.key === "try" ? undefined : t.key }) }))} active={tab} />
      {sp.review_error && <div className="error">{sp.review_error}</div>}
      {sp.review_notice && <div className="note-panel">{sp.review_notice}</div>}
      {tab === "try" && <Try agents={live} />}
      {tab === "attacks" && <Attacks agents={live} />}
      {tab === "suites" && <Suites />}
      {tab === "reliability" && <Reliability agents={live} />}
      {tab === "ci" && <Ci />}
    </>
  );
}

async function Try({ agents }: { agents: any[] }) {
  // The first agent's own tools; the picker loads another agent's when it changes.
  const tools = agents.length ? await safeApi<any>(`/api/agents/${encodeURIComponent(agents[0].slug)}/tools`, { tools: [] }) : { tools: [] };
  return (
    <Card title="Check a message or tool call" hint="Runs your real rules for the chosen agent. Not counted as production traffic.">
      {agents.length ? (
        <TryIt agents={agents.map((a) => ({ slug: a.slug, name: a.name }))} tools={tools.tools || []} />
      ) : (
        <Empty action={<Link href="/app/start" className="k-btn-primary">Connect an agent</Link>}>No agents yet.</Empty>
      )}
    </Card>
  );
}

async function Attacks({ agents }: { agents: any[] }) {
  const campaigns = await safeApi<any>("/api/redteam/campaigns", { campaigns: [] });
  const list: any[] = campaigns.campaigns || [];
  const last = list[0];
  return (
    <>
      <Card title="Run attack test" hint="Runs the built-in attack library against the agent's real permissions and rules. A pass means these attacks were stopped, not that every attack would be.">
        <form action="/api/redteam/campaigns" method="POST" className="k-pills" style={{ gap: 8 }}>
          <select className="k-select" name="agent" required defaultValue="" aria-label="Agent">
            <option value="" disabled>Choose an agent</option>
            {agents.map((a) => (
              <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>
            ))}
          </select>
          <button type="submit" className="k-btn-primary">Run</button>
        </form>
      </Card>
      {last && (
        <Grid cols={3}>
          <Kpi label="Attacks tried (last run)" value={num(last.summary?.probes_run || 0)} />
          <Kpi label="Stopped" value={num(last.summary?.attacks_blocked || 0)} />
          <Kpi label="Got through" value={num(last.summary?.attacks_succeeded || 0)} tone={last.summary?.attacks_succeeded ? "bad" : "ok"} />
        </Grid>
      )}
      <Card title="Past runs" flush>
        {list.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Run</th>
                <th className="num">Attacks</th>
                <th className="num">Stopped</th>
                <th className="num">Got through</th>
                <th className="tight">Score</th>
                <th className="tight">When</th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td className="num">{num(c.summary?.probes_run || 0)}</td>
                  <td className="num">{num(c.summary?.attacks_blocked || 0)}</td>
                  <td className="num">{c.summary?.attacks_succeeded ? <Pill tone="bad">{c.summary.attacks_succeeded}</Pill> : "0"}</td>
                  <td className="tight">
                    <Pill tone={(c.summary?.posture_score ?? 0) >= 0.9 ? "ok" : "warn"}>{Math.round((c.summary?.posture_score ?? 0) * 100)}%</Pill>
                  </td>
                  <td className="tight muted">{ago(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No attack tests yet.</Empty>
        )}
      </Card>
    </>
  );
}

async function Suites() {
  const [suites, runs] = await Promise.all([
    safeApi<any>("/api/eval/suites", { suites: [] }),
    safeApi<any>("/api/eval/runs?limit=20", { runs: [] }),
  ]);
  const lastBySuite: Record<string, any> = {};
  for (const r of runs.runs || []) if (!lastBySuite[r.suite_id]) lastBySuite[r.suite_id] = r;
  const passRate = (r: any) => {
    const rates = Object.values(r?.summary?.scorers || {}).map((v: any) => v.pass_rate).filter((v: any) => v != null) as number[];
    return rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : null;
  };
  return (
    <>
      <Card flush title="Suites" action={<Link href="/app/evals">Details</Link>}>
        {suites.suites?.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Suite</th>
                <th className="num">Cases</th>
                <th className="tight">Last run</th>
                <th className="tight">Pass rate</th>
              </tr>
            </thead>
            <tbody>
              {suites.suites.map((s: any) => {
                const last = lastBySuite[s.id];
                const rate = passRate(last);
                return (
                  <tr key={s.id}>
                    <td>
                      <Link className="k-name" href={`/app/evals/${encodeURIComponent(s.key)}`}>{s.name || s.key}</Link>
                      {s.description && <span className="sub">{s.description}</span>}
                    </td>
                    <td className="num">{num(s.cases)}</td>
                    <td className="tight muted">{last ? ago(last.created_at) : "Never"}</td>
                    <td className="tight">
                      {rate == null ? <span className="k-muted">—</span> : <Pill tone={rate >= 0.9 ? "ok" : rate >= 0.7 ? "warn" : "bad"}>{Math.round(rate * 100)}%</Pill>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <Empty>No suites yet.</Empty>
        )}
      </Card>
      <Card title="New suite">
        <form action="/api/eval/suites" method="POST" className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
          <input className="k-input" name="key" required placeholder="support-quality" aria-label="Suite ID" />
          <input className="k-input" name="name" placeholder="Name" aria-label="Suite name" />
          <input className="k-input" name="description" placeholder="Description" aria-label="Description" style={{ minWidth: 260 }} />
          <button type="submit" className="k-btn-primary">Create</button>
        </form>
      </Card>
    </>
  );
}

async function Reliability({ agents }: { agents: any[] }) {
  const [slos, scorers] = await Promise.all([
    safeApi<any>("/api/eval/slos", { slos: [] }),
    safeApi<any>("/api/eval/scorers", { scorers: [] }),
  ]);
  return (
    <>
      <Card title="Targets" flush>
        {slos.slos?.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Measure</th>
                <th className="num">Target</th>
                <th className="num">Actual</th>
                <th className="num">Budget left</th>
              </tr>
            </thead>
            <tbody>
              {slos.slos.map((s: any) => (
                <tr key={s.slo_id}>
                  <td><Link href={`/app/agents/${encodeURIComponent(s.agent)}?tab=quality`}>{s.agent}</Link></td>
                  <td>{s.scorer}{s.objective && <span className="sub">{s.objective}</span>}</td>
                  <td className="num">{s.target != null ? `${Math.round(s.target * 100)}%` : "—"}</td>
                  <td className="num">{s.attainment != null ? `${Math.round(s.attainment * 100)}%` : <span className="k-muted">No data</span>}</td>
                  <td className="num">{s.error_budget_remaining != null ? `${Math.round(s.error_budget_remaining * 100)}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No targets yet.</Empty>
        )}
      </Card>
      <Grid cols={2}>
        <Card title="New target">
          <form action="/api/eval/slos" method="POST" className="k-form">
            <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
              <select className="k-select" name="agent" required defaultValue="" aria-label="Agent">
                <option value="" disabled>Agent</option>
                {agents.map((a) => <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>)}
              </select>
              <select className="k-select" name="scorer" required defaultValue="" aria-label="Measure">
                <option value="" disabled>Measure</option>
                {(scorers.scorers || []).map((s: any) => <option key={s.key} value={s.key}>{s.key}</option>)}
              </select>
              <select className="k-select" name="window" defaultValue="7d" aria-label="Window">
                <option value="1d">1 day</option>
                <option value="7d">7 days</option>
                <option value="30d">30 days</option>
              </select>
              <input className="k-input" type="number" name="target" step="0.01" min="0" max="1" defaultValue="0.9" style={{ width: 90 }} aria-label="Target (0–1)" />
            </div>
            <input className="k-input" name="objective" placeholder="95% of answers stay grounded" aria-label="Objective" />
            <div><button type="submit" className="k-btn-primary">Add target</button></div>
          </form>
        </Card>
        <Card title="Score real traffic" hint="Grades recent production runs with the same scorers as test suites.">
          <form action="/api/eval/online" method="POST" className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
            <select className="k-select" name="agent" required defaultValue="" aria-label="Agent">
              <option value="" disabled>Agent</option>
              {agents.map((a) => <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>)}
            </select>
            <select className="k-select" name="since_days" defaultValue="7" aria-label="Period">
              <option value="1">Last day</option>
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
            </select>
            <button type="submit" className="k-btn-primary">Score</button>
          </form>
        </Card>
      </Grid>
    </>
  );
}

function Ci() {
  const gateway = publicApiBase();
  return (
    <>
      <Card title="Block a release when quality drops">
        <div className="k-form">
          <CodeSnippet label="Save the current run as the baseline" code="agentfox test baseline RUN_ID --label main" />
          <CodeSnippet label="In CI: fail on regression" code="agentfox test gate SUITE --baseline RUN_ID" />
          <CodeSnippet label="Or over HTTP" code={`curl -s -X POST ${gateway}/api/eval/gate \\\n  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\\n  -H "Content-Type: application/json" \\\n  -d '{"suite": "SUITE", "min_pass_rate": 0.9}'`} />
        </div>
      </Card>
      <Card title="Attack test in CI">
        <CodeSnippet code="agentfox test redteam AGENT --adaptive" />
      </Card>
    </>
  );
}
