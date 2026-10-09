import type { Metadata } from "next";
import Link from "next/link";
import { safeApi } from "@/lib/product/api";
import { appPageMetadata } from "@/lib/site";
import {
  BarList,
  Card,
  Empty,
  Grid,
  Header,
  Kpi,
  Pill,
  Sparkline,
  Tabs,
  TimeChart,
  ago,
  money,
  num,
  pctOf,
  type BarRow,
} from "@/components/kit";
import { FilterBar } from "@/components/kit/FilterBar";
import { filtersFrom, metricsQs, observeTabs, runsHref, type Filters } from "@/lib/product/observe";
import { ensureRange } from "@/lib/product/range";
import { RangeProvider } from "@/components/kit/RangeContext";
import { CATEGORIES, categoryLabel, detectorName, dimLabel, ruleCategory, ruleTitle } from "@/lib/product/vocab";

export const metadata: Metadata = appPageMetadata("Observe");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

export default async function Observe({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  await ensureRange("/app/observe", sp);
  const f = filtersFrom(sp);
  const tab = ["breaks", "security", "review", "cost"].includes(sp.tab || "") ? sp.tab! : "overview";

  const [agents, envs] = await Promise.all([
    safeApi<any>("/api/agents", { agents: [] }),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs({ range: "90d" }, { dim: "environment" })}`, { rows: [] }),
  ]);

  return (
    <RangeProvider range={sp.range}>
    <>
      <Header title="Observe" />
      <Tabs items={observeTabs(f)} active={tab} />
      <FilterBar
        agents={(agents.agents || []).map((a: any) => ({ slug: a.slug, name: a.name }))}
        environments={(envs.rows || []).map((r: any) => r.key)}
      />
      {tab === "overview" && <Overview f={f} />}
      {tab === "breaks" && <Breaks f={f} />}
      {tab === "security" && <Security f={f} agents={agents} />}
      {tab === "review" && <Review f={f} agents={agents.agents || []} />}
      {tab === "cost" && <Cost f={f} />}
    </>
    </RangeProvider>
  );
}

const EMPTY_SUMMARY = {
  buckets: [],
  bucket_seconds: 3600,
  totals: { requests: 0, allowed: 0, masked: 0, held: 0, blocked: 0, errors: 0, cost_usd: 0, agents: 0 },
  previous: { requests: 0, allowed: 0, masked: 0, held: 0, blocked: 0, errors: 0, cost_usd: 0, agents: 0 },
  latency_ms: { p50: 0, p95: 0 },
};

function series(buckets: any[], pick: (b: any) => number): number[] {
  return buckets.map(pick);
}

function breakdownRows(rows: any[], f: Filters, link: (key: string) => string | undefined): BarRow[] {
  return rows.map((r: any) => ({
    key: r.key,
    label: dimLabel(r.key),
    href: r.key === "(unknown)" ? undefined : link(r.key),
    value: r.requests,
    segments: r,
  }));
}

async function Overview({ f }: { f: Filters }) {
  const [s, byAgent, byTool, byModel, rules] = await Promise.all([
    safeApi<any>(`/api/metrics/summary?${metricsQs(f)}`, EMPTY_SUMMARY),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs(f, { dim: "agent" })}`, { rows: [] }),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs(f, { dim: "tool" })}`, { rows: [] }),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs(f, { dim: "model" })}`, { rows: [] }),
    safeApi<any>(`/api/metrics/rules?${metricsQs(f)}`, { rules: [] }),
  ]);
  const t = s.totals;
  const p = s.previous;
  const b = s.buckets;

  if (!t.requests && !p.requests) {
    return (
      <Card>
        <Empty action={<Link href="/app/start" className="k-btn-primary">Connect an agent</Link>}>
          No requests in this period.
        </Empty>
      </Card>
    );
  }

  return (
    <>
      <Grid cols={6}>
        <Kpi label="Requests" value={num(t.requests)} current={t.requests} prev={p.requests} better="none" href={runsHref(f)} spark={series(b, (x) => x.allowed + x.masked + x.held + x.blocked)} />
        <Kpi label="Blocked" value={num(t.blocked)} current={t.blocked} prev={p.blocked} href={runsHref(f, { outcome: "blocked" })} spark={series(b, (x) => x.blocked)} />
        <Kpi label="Held for a person" value={num(t.held)} current={t.held} prev={p.held} href={runsHref(f, { outcome: "held" })} spark={series(b, (x) => x.held)} />
        <Kpi label="Masked" value={num(t.masked)} current={t.masked} prev={p.masked} better="none" href={runsHref(f, { outcome: "masked" })} spark={series(b, (x) => x.masked)} />
        <Kpi label="Errors" value={num(t.errors)} current={t.errors} prev={p.errors} tone={t.errors ? "bad" : undefined} href={runsHref(f, { errors: true })} spark={series(b, (x) => x.errors || 0)} />
        <Kpi label="Check time (p95)" value={`${num(s.latency_ms.p95)} ms`} hint="Time AgentFox adds to each request, 95th percentile." />
      </Grid>

      <Card title="Requests">
        <TimeChart buckets={b} bucketSeconds={s.bucket_seconds} linkFor={(start, end) => runsHref(f, { start, end })} />
      </Card>

      <Grid cols={2}>
        <Card title="By agent" action={<Link href="/app/agents">All agents</Link>}>
          <BarList rows={breakdownRows(byAgent.rows, f, (k) => `/app/agents/${encodeURIComponent(k)}`)} />
        </Card>
        <Card title="By tool">
          <BarList rows={breakdownRows(byTool.rows, f, (k) => runsHref(f, { tool: k }))} empty="No tool calls" />
        </Card>
      </Grid>
      <Grid cols={2}>
        <Card title="Rules triggered" action={<Link href="/app/policies?tab=performance">Performance</Link>}>
          <BarList
            empty="No rules triggered"
            rows={rules.rules.map((r: any) => ({
              key: r.rule_id,
              label: ruleTitle(r.rule_id),
              href: `/app/policies/rules/${encodeURIComponent(r.rule_id)}`,
              value: r.fires,
              note: r.watched && !r.enforced ? "watching" : undefined,
            }))}
          />
        </Card>
        <Card title="By model">
          <BarList rows={breakdownRows(byModel.rows, f, () => undefined)} empty="No model calls" />
        </Card>
      </Grid>
    </>
  );
}

/** True when no rule in force covers the area, so its 0 would mean "not looking". */
function notChecked(rules: any, category: string): boolean {
  return rules.checked ? rules.checked[category] === false : false;
}

function byCategory(rules: any[]) {
  const out: Record<string, { fires: number; enforced: number; watched: number; series: number[]; rules: any[] }> = {};
  for (const r of rules) {
    const c = r.category || ruleCategory(r.rule_id);
    const g = (out[c] ||= { fires: 0, enforced: 0, watched: 0, series: [], rules: [] });
    g.fires += r.fires;
    g.enforced += r.enforced;
    g.watched += r.watched;
    g.series = r.series.map((v: number, i: number) => v + (g.series[i] || 0));
    g.rules.push(r);
  }
  return out;
}

async function Breaks({ f }: { f: Filters }) {
  const [rules, errors, findings] = await Promise.all([
    safeApi<any>(`/api/metrics/rules?${metricsQs(f)}`, { rules: [] }),
    safeApi<any>(`/api/metrics/errors?${metricsQs(f)}`, { rows: [] }),
    safeApi<any>(`/api/findings?status=open${f.agent ? `&agent=${f.agent}` : ""}`, { findings: [] }),
  ]);
  const cats = byCategory(rules.rules);
  const errorTotal = errors.rows.reduce((n: number, r: any) => n + r.count, 0);
  const tiles = ["attacks", "data", "actions", "quality"] as const;

  return (
    <>
      <Grid cols={5}>
        {tiles.map((c) =>
          notChecked(rules, c) ? (
            <Kpi key={c} label={categoryLabel(c)} value="Not checked" hint="No rule in force looks for this. Add one in Policies." href="/app/policies/new" />
          ) : (
            <Kpi key={c} label={categoryLabel(c)} value={num(cats[c]?.fires || 0)} spark={cats[c]?.series} href="#rules" />
          ),
        )}
        <Kpi label="Failed steps" value={num(errorTotal)} tone={errorTotal ? "bad" : undefined} href={runsHref(f, { errors: true })} />
      </Grid>

      <div id="rules" />
      <Card title="What triggered" flush>
        {rules.rules.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Area</th>
                <th className="num">Fired</th>
                <th className="num">Stopped</th>
                <th className="num">Watching</th>
                <th>Trend</th>
                <th>Most affected</th>
                <th>Last</th>
              </tr>
            </thead>
            <tbody>
              {CATEGORIES.flatMap((c) => (cats[c.key]?.rules || []).map((r: any) => ({ ...r, cat: c.label }))).map((r: any) => (
                <tr key={r.rule_id}>
                  <td>
                    <Link className="k-name" href={`/app/policies/rules/${encodeURIComponent(r.rule_id)}`}>
                      {ruleTitle(r.rule_id)}
                    </Link>
                  </td>
                  <td className="muted">{r.cat}</td>
                  <td className="num">
                    <Link href={runsHref(f, { rule: r.rule_id })}>{num(r.fires)}</Link>
                  </td>
                  <td className="num">{num(r.enforced)}</td>
                  <td className="num">{r.watched ? <Pill tone="outline">{num(r.watched)}</Pill> : "0"}</td>
                  <td>
                    <Sparkline values={r.series} />
                  </td>
                  <td className="muted">{Object.keys(r.agents)[0] || "—"}</td>
                  <td className="muted">{ago(r.last_fired)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>Nothing triggered in this period.</Empty>
        )}
      </Card>

      <Grid cols={2}>
        <Card title="Failed steps" flush>
          {errors.rows.length ? (
            <table className="k-table">
              <thead>
                <tr>
                  <th>Step</th>
                  <th className="num">Count</th>
                  <th>Last</th>
                </tr>
              </thead>
              <tbody>
                {errors.rows.map((e: any) => (
                  <tr key={`${e.kind}-${e.name}`}>
                    <td>
                      <Link className="k-name" href={`/app/traces/${e.sample_trace_id}`}>
                        {e.name}
                      </Link>
                      <span className="sub">{e.message}</span>
                    </td>
                    <td className="num">{num(e.count)}</td>
                    <td className="muted">{ago(e.last)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No failed steps.</Empty>
          )}
        </Card>
        <Card title="Open issues" action={<Link href="/app/findings">All issues</Link>} flush>
          {findings.findings?.length ? (
            <ul className="k-list">
              {findings.findings.slice(0, 6).map((x: any) => (
                <li key={x.id}>
                  <div className="k-list-main">
                    <Link href={`/app/findings/${x.id}`}>{x.title}</Link>
                    <span className="muted">{x.agent_slug || ""}</span>
                  </div>
                  <Pill tone={x.severity === "critical" ? "bad" : x.severity === "high" ? "held" : "neutral"}>{x.severity}</Pill>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No open issues.</Empty>
          )}
        </Card>
      </Grid>
    </>
  );
}

async function Security({ f, agents }: { f: Filters; agents: any }) {
  const [rules, byTool, byAgent] = await Promise.all([
    safeApi<any>(`/api/metrics/rules?${metricsQs(f)}`, { rules: [] }),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs(f, { dim: "tool" })}`, { rows: [] }),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs(f, { dim: "agent" })}`, { rows: [] }),
  ]);
  const cats = byCategory(rules.rules);
  const ruleRows = (c: string): BarRow[] =>
    (cats[c]?.rules || []).map((r: any) => ({
      key: r.rule_id,
      label: ruleTitle(r.rule_id),
      href: `/app/policies/rules/${encodeURIComponent(r.rule_id)}`,
      value: r.fires,
      note: r.watched && !r.enforced ? "watching" : undefined,
    }));
  const stopped = (rows: any[]) =>
    rows
      .map((r: any) => ({ key: r.key, value: r.held + r.blocked, r }))
      .filter((r) => r.value > 0)
      .sort((a, b) => b.value - a.value);
  const shadow = agents.inventory?.shadow || 0;

  return (
    <>
      <Grid cols={4}>
        <Kpi label="Attacks seen" value={notChecked(rules, "attacks") ? "Not checked" : num(cats.attacks?.fires || 0)} spark={cats.attacks?.series} href={runsHref(f, { outcome: "blocked" })} />
        <Kpi label="Sensitive data caught" value={notChecked(rules, "data") ? "Not checked" : num(cats.data?.fires || 0)} spark={cats.data?.series} />
        <Kpi label="Risky actions stopped" value={num(cats.actions?.enforced || 0)} spark={cats.actions?.series} href={runsHref(f, { outcome: "held" })} />
        <Kpi label="Unregistered agents" value={num(shadow)} tone={shadow ? "bad" : undefined} href="/app/agents?tab=attention" />
      </Grid>
      <Grid cols={2}>
        <Card title="Attack types">
          <BarList rows={ruleRows("attacks")} empty="No attacks seen" />
        </Card>
        <Card title="Sensitive data">
          <BarList rows={ruleRows("data")} empty="No sensitive data caught" />
        </Card>
      </Grid>
      <Grid cols={2}>
        <Card title="Risky actions by tool">
          <BarList
            empty="No risky actions"
            rows={stopped(byTool.rows).map(({ key, value, r }) => ({ key, label: key, value, segments: { held: r.held, blocked: r.blocked }, href: runsHref(f, { tool: key }) }))}
          />
        </Card>
        <Card title="Most targeted agents">
          <BarList
            empty="No agents targeted"
            rows={stopped(byAgent.rows).map(({ key, value, r }) => ({ key, label: key, value, segments: { held: r.held, blocked: r.blocked }, href: `/app/agents/${encodeURIComponent(key)}` }))}
          />
        </Card>
      </Grid>
    </>
  );
}

async function Review({ f, agents }: { f: Filters; agents: any[] }) {
  const statuses = ["pending", "approved", "denied", "expired"] as const;
  const agentQs = f.agent ? `?agent=${encodeURIComponent(f.agent)}` : "";
  const [lists, report] = await Promise.all([
    Promise.all(statuses.map((s) => safeApi<any>(`/api/approvals?status=${s}`, { approvals: [] }))),
    safeApi<any>(`/api/escalation/report${agentQs}`, null),
  ]);
  const days = { "24h": 1, "7d": 7, "30d": 30, "90d": 90 }[f.range];
  const since = Date.now() - days * 86400_000;
  const slug: Record<string, string> = Object.fromEntries(agents.map((a) => [a.id, a.slug]));
  const inWindow = (a: any) =>
    Date.parse(a.requested_at) >= since && (!f.agent || slug[a.agent_id] === f.agent);
  const by = Object.fromEntries(statuses.map((s, i) => [s, (lists[i].approvals || []).filter(inWindow)])) as Record<
    (typeof statuses)[number],
    any[]
  >;
  const all = statuses.flatMap((s) => by[s]);
  const count = (key: (a: any) => string) => {
    const m: Record<string, number> = {};
    for (const a of all) m[key(a)] = (m[key(a)] || 0) + 1;
    return Object.entries(m)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ key: k, label: k, value: v }));
  };

  return (
    <>
      <Grid cols={4}>
        <Kpi label="Waiting" value={num(by.pending.length)} tone={by.pending.length ? "warn" : undefined} href="/app/approvals" />
        <Kpi label="Approved" value={num(by.approved.length)} href="/app/approvals?tab=history&status=approved" />
        <Kpi label="Denied" value={num(by.denied.length)} href="/app/approvals?tab=history&status=denied" />
        <Kpi label="Expired" value={num(by.expired.length)} tone={by.expired.length ? "warn" : undefined} hint="Nobody answered in time; the action was denied." href="/app/approvals?tab=history&status=expired" />
      </Grid>
      <Grid cols={2}>
        <Card title="Held by tool">
          <BarList rows={count((a) => a.tool || "—")} empty="Nothing held" />
        </Card>
        <Card title="Held by agent">
          <BarList rows={count((a) => slug[a.agent_id] || "—")} empty="Nothing held" />
        </Card>
      </Grid>
      {report && (
        <Card title="Hand-offs to people" action={<Link href="/app/approvals?tab=handoffs">Open</Link>}>
          <Grid cols={4}>
            <Kpi label="Hand-offs" value={num(report.handoffs)} />
            <Kpi label="Missed" value={num(report.missed_escalations)} tone={report.missed_escalations ? "bad" : undefined} hint="Conversations that should have reached a person and didn't." />
            <Kpi label="Incomplete" value={num(report.incomplete_handoffs)} />
            <Kpi label="Missed rate" value={pctOf(report.missed_escalations, report.qualified_for_escalation || 0)} />
          </Grid>
        </Card>
      )}
    </>
  );
}

async function Cost({ f }: { f: Filters }) {
  const days = { "24h": 1, "7d": 7, "30d": 30, "90d": 90 }[f.range];
  const [s, byAgent, byModel, latency] = await Promise.all([
    safeApi<any>(`/api/metrics/summary?${metricsQs(f)}`, EMPTY_SUMMARY),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs(f, { dim: "agent" })}`, { rows: [] }),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs(f, { dim: "model" })}`, { rows: [] }),
    safeApi<any>(`/api/guardrails/latency?days=${days}${f.agent ? `&agent=${f.agent}` : ""}`, { per_detector: {} }),
  ]);
  const t = s.totals;
  const costRows = (rows: any[]): BarRow[] =>
    rows
      .filter((r: any) => r.cost_usd > 0)
      .sort((a: any, b: any) => b.cost_usd - a.cost_usd)
      .map((r: any) => ({ key: r.key, label: dimLabel(r.key), value: r.cost_usd }));
  const detectors: BarRow[] = Object.entries(latency.per_detector || {})
    .map(([k, v]: [string, any]) => ({ key: k, label: detectorName(k), value: v.p95_ms, note: `${num(v.runs)} runs` }))
    .sort((a, b) => b.value - a.value);

  return (
    <>
      <Grid cols={5}>
        <Kpi label="Model cost" value={money(t.cost_usd)} current={t.cost_usd} prev={s.previous.cost_usd} />
        <Kpi label="Per request" value={money(t.requests ? t.cost_usd / t.requests : 0)} />
        <Kpi label="Requests" value={num(t.requests)} current={t.requests} prev={s.previous.requests} better="none" />
        <Kpi label="Check time (p50)" value={`${num(s.latency_ms.p50)} ms`} />
        <Kpi label="Check time (p95)" value={`${num(s.latency_ms.p95)} ms`} />
      </Grid>
      <Grid cols={2}>
        <Card title="Cost by agent">
          <BarList rows={costRows(byAgent.rows)} format={money} empty="No model cost recorded" />
        </Card>
        <Card title="Cost by model">
          <BarList rows={costRows(byModel.rows)} format={money} empty="No model cost recorded" />
        </Card>
      </Grid>
      <Card title="Check time by detector" hint="95th percentile per detector.">
        <BarList rows={detectors} format={(n) => `${n} ms`} empty="No detector runs" />
      </Card>
    </>
  );
}
