import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { ApiError, api, apiErrorProps, safeApi } from "@/lib/product/api";
import { ApiDown, NotFound } from "@/components/ui";
import {
  ActionPill,
  BarList,
  Card,
  Empty,
  Grid,
  Header,
  Kpi,
  Meta,
  ModePill,
  Pill,
  SeverityPill,
  Sparkline,
  Tabs,
  TimeChart,
  ago,
  href,
  num,
  pctOf,
} from "@/components/kit";
import { FilterBar } from "@/components/kit/FilterBar";
import { RunsTable } from "@/components/kit/RunsTable";
import { AgentMap } from "@/components/product/AgentMap";
import { AccessEditor } from "@/components/product/agent/AccessEditor";
import { RANGE_DAYS, metricsQs, runsHref, verdictsFor, type Filters } from "@/lib/product/observe";
import { CATEGORIES, categoryLabel, rangeOf, ruleCategory, ruleTitle } from "@/lib/product/vocab";
import { ensureRange } from "@/lib/product/range";
import { GuardrailMapLazy as GuardrailMap } from "@/components/product/agent/GuardrailMapLazy";
import { RangeProvider } from "@/components/kit/RangeContext";

export const metadata: Metadata = appPageMetadata("Agent");
export const dynamic = "force-dynamic";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "map", label: "Map" },
  { key: "access", label: "Access" },
  { key: "rules", label: "Rules" },
  { key: "activity", label: "Activity" },
  { key: "quality", label: "Quality" },
  { key: "settings", label: "Settings" },
];

/** Old tab names, so bookmarked links still land somewhere sensible. */
const LEGACY: Record<string, string> = { permissions: "rules", registration: "settings" };

type SP = Record<string, string | undefined>;

export default async function AgentDetail({ params, searchParams }: { params: Promise<{ slug: string }>; searchParams: Promise<SP> }) {
  const { slug } = await params;
  const sp = await searchParams;
  const requested = LEGACY[sp.tab || ""] || sp.tab;
  const tab = TABS.some((t) => t.key === requested) ? requested! : "overview";
  // One round of requests, in parallel: the range (when the URL names none), the
  // agent, and its kill-switch state.
  const needsRange = ["overview", "rules", "activity"].includes(tab);
  const [, outcome, controls] = await Promise.all([
    needsRange ? ensureRange(`/app/agents/${encodeURIComponent(slug)}`, sp, slug) : Promise.resolve(),
    api(`/api/agents/${encodeURIComponent(slug)}/posture`).then(
      (posture: any) => ({ posture, error: null as any }),
      (error: any) => ({ posture: null, error }),
    ),
    safeApi<any>("/api/agent-controls", { controls: [] }),
  ]);
  const f: Filters = { range: rangeOf(sp.range), agent: slug };

  if (outcome.error) {
    const e = outcome.error;
    return (
      <>
        <Header title={slug} back={{ href: "/app/agents", label: "Agents" }} />
        {e instanceof ApiError && e.status === 404 ? (
          <NotFound what="agent" detail={slug} back={{ href: "/app/agents", label: "Agents" }} />
        ) : (
          <ApiDown {...apiErrorProps(e)} />
        )}
      </>
    );
  }
  const posture = outcome.posture;
  const a = posture.agent;
  const state = (controls.controls || []).find((c: any) => c.agent === a.slug)?.state || "active";
  const tabHref = (k: string) => href(`/app/agents/${encodeURIComponent(slug)}`, { tab: k === "overview" ? undefined : k, range: sp.range });

  return (
    <RangeProvider range={sp.range}>
    <>
      <Header
        back={{ href: "/app/agents", label: "Agents" }}
        title={a.name || a.slug}
        meta={
          <>
            {state === "active" ? <Pill tone="ok">Active</Pill> : <Pill tone="bad">{state === "killed" ? "Stopped" : "Paused"}</Pill>}
            {a.risk_tier === "high" && <Pill tone="held">High risk</Pill>}
            {!a.registered && <Pill tone="bad">Unregistered</Pill>}
            {a.is_seed && <Pill tone="outline">Sample</Pill>}
          </>
        }
        actions={
          <>
          <Link className="k-btn-primary" href={`/app/agents/${encodeURIComponent(a.slug)}/protect`}>
            Protect
          </Link>
          <form action={`/api/agents/${encodeURIComponent(a.slug)}/control`} method="POST">
            <input type="hidden" name="action" value={state === "active" ? "quarantine" : "resume"} />
            <button type="submit" className={state === "active" ? "k-btn-danger" : "k-btn"}>
              {state === "active" ? "Pause agent" : "Resume agent"}
            </button>
          </form>
          </>
        }
      />
      <Meta
        items={[
          ["Owner", a.owner_email || <Link href={tabHref("settings")}>Assign</Link>],
          ["Team", a.owner_team || "—"],
          ["Environment", a.environment],
          ["Framework", a.framework || "—"],
          ["Last active", ago(a.last_seen_at)],
        ]}
      />
      <div style={{ height: 14 }} />
      {sp.review_error && <div className="error">{sp.review_error}</div>}
      {sp.review_notice && <div className="note-panel">Done: {sp.review_notice}.</div>}
      <Tabs items={TABS.map((t) => ({ ...t, href: tabHref(t.key) }))} active={tab} />

      {tab === "overview" && <Overview f={f} posture={posture} />}
      {tab === "map" && <MapTab slug={slug} />}
      {tab === "access" && <Access slug={slug} prefill={sp.grant} />}
      {tab === "rules" && <Rules f={f} slug={slug} />}
      {tab === "activity" && <Activity f={f} outcome={sp.outcome} />}
      {tab === "quality" && <Quality slug={slug} posture={posture} />}
      {tab === "settings" && <Settings a={a} state={state} />}
    </>
    </RangeProvider>
  );
}

async function Overview({ f, posture }: { f: Filters; posture: any }) {
  const [s, rules, lineage] = await Promise.all([
    safeApi<any>(`/api/metrics/summary?${metricsQs(f)}`, null),
    safeApi<any>(`/api/metrics/rules?${metricsQs(f)}`, { rules: [] }),
    safeApi<any>(`/api/agents/${encodeURIComponent(f.agent!)}/lineage?depth=2`, { nodes: [], links: [], blast_radius: 0 }),
  ]);
  const t = s?.totals || {};
  const p = s?.previous || {};
  const b = s?.buckets || [];
  const findings: any[] = posture.open_findings || [];
  return (
    <>
      <FilterBar />
      <Grid cols={4}>
        <Kpi label="Requests" value={num(t.requests || 0)} current={t.requests} prev={p.requests} better="none" href={runsHref(f)} spark={b.map((x: any) => x.allowed + x.masked + x.held + x.blocked)} />
        <Kpi label="Blocked" value={num(t.blocked || 0)} current={t.blocked} prev={p.blocked} href={runsHref(f, { outcome: "blocked" })} spark={b.map((x: any) => x.blocked)} />
        <Kpi label="Held for a person" value={num(t.held || 0)} current={t.held} prev={p.held} href={runsHref(f, { outcome: "held" })} spark={b.map((x: any) => x.held)} />
        <Kpi label="Errors" value={num(t.errors || 0)} current={t.errors} prev={p.errors} tone={t.errors ? "bad" : undefined} href={runsHref(f, { errors: true })} />
      </Grid>
      {s && (
        <Card title="Requests">
          <TimeChart buckets={b} bucketSeconds={s.bucket_seconds} height={110} linkFor={(start, end) => runsHref(f, { start, end })} />
        </Card>
      )}
      <Grid cols={2}>
        <Card title="Rules triggered">
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
        <Card title="Open issues" action={<Link href={`/app/findings?agent=${encodeURIComponent(f.agent!)}`}>All</Link>} flush>
          {findings.length ? (
            <ul className="k-list">
              {findings.slice(0, 6).map((x) => (
                <li key={x.id}>
                  <div className="k-list-main">
                    <Link href={`/app/findings/${x.id}`}>{x.title}</Link>
                  </div>
                  <SeverityPill value={x.severity} />
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No open issues.</Empty>
          )}
        </Card>
      </Grid>
      {lineage.links?.length > 0 && (
        <AgentMap root={lineage.root || f.agent!} nodes={lineage.nodes || []} links={lineage.links} blastRadius={lineage.blast_radius ?? 0} />
      )}
    </>
  );
}

async function Access({ slug, prefill }: { slug: string; prefill?: string }) {
  const [access, boundaries] = await Promise.all([
    safeApi<any>(`/api/agents/${encodeURIComponent(slug)}/access`, null),
    safeApi<any>("/api/answerability/boundaries", { boundaries: [], question_types: [] }),
  ]);
  const boundary = (boundaries.boundaries || []).find((b: any) => b.agent === slug) || null;
  const types: string[] = boundaries.question_types?.length ? boundaries.question_types : ["fact", "aggregate", "prediction", "opinion", "procedure"];
  return (
    <>
      {access ? (
        <AccessEditor
          slug={slug}
          capabilities={access.capabilities}
          tried={access.tried}
          tools={access.tools}
          unused={access.unused}
          inCode={access.in_code || []}
          prefill={prefill}
        />
      ) : (
        <Card>
          <Empty>Access could not be loaded.</Empty>
        </Card>
      )}
      <Card
        title="What it may answer"
        hint="Questions outside this are refused before the model answers."
        action={<Link href={href("/app/policies/new", { from: "custom", agent: slug })}>Topic rule</Link>}
      >
        <form action={`/api/agents/${encodeURIComponent(slug)}/boundary`} method="POST" className="k-form">
          <div className="k-field">
            <label htmlFor="b-sor">Sources it answers from</label>
            <input id="b-sor" className="k-input" name="systems_of_record" defaultValue={boundary?.systems_of_record?.join(", ") || ""} placeholder="price-book, ticket-history" />
          </div>
          <div className="k-field">
            <label htmlFor="b-ent">Topics it knows</label>
            <input id="b-ent" className="k-input" name="entity_types" defaultValue={boundary?.entity_types?.join(", ") || ""} placeholder="customer, order, invoice" />
          </div>
          <div className="k-field">
            <label htmlFor="b-out">Topics it refuses</label>
            <input id="b-out" className="k-input" name="out_of_scope_topics" defaultValue={boundary?.out_of_scope_topics?.join(", ") || ""} placeholder="legal advice, medical diagnosis" />
          </div>
          <div className="k-field">
            <label htmlFor="b-cov">History covered</label>
            <span className="k-pills">
              <input id="b-cov" className="k-input" style={{ width: 90 }} type="number" min={0} name="coverage_months" defaultValue={boundary?.coverage_months ?? ""} />
              <span className="k-muted">months</span>
              <input className="k-input" style={{ width: 90, marginLeft: 12 }} type="number" min={0} name="freshness_hours" defaultValue={boundary?.freshness_hours ?? ""} aria-label="Freshness in hours" />
              <span className="k-muted">hours fresh</span>
            </span>
          </div>
          <div className="k-field">
            <label>Question types</label>
            <span className="k-pills" style={{ flexWrap: "wrap", gap: 14 }}>
              {types.map((qt) => (
                <label key={qt} className="k-check">
                  <input type="checkbox" name="answerable_types" value={qt} defaultChecked={boundary ? boundary.answerable_types?.includes(qt) : true} />
                  {qt}
                </label>
              ))}
            </span>
          </div>
          <div className="k-field">
            <span />
            <span>
              <button type="submit" className="k-btn-primary">
                {boundary ? "Save" : "Set boundary"}
              </button>
            </span>
          </div>
        </form>
      </Card>
    </>
  );
}

async function Rules({ f, slug }: { f: Filters; slug: string }) {
  const [effective, stats] = await Promise.all([
    safeApi<any>(`/api/policies/effective?agent=${encodeURIComponent(slug)}`, { rules: [] }),
    safeApi<any>(`/api/metrics/rules?${metricsQs({ ...f, range: "30d" })}`, { rules: [] }),
  ]);
  const byId: Record<string, any> = Object.fromEntries((stats.rules || []).map((r: any) => [r.rule_id, r]));
  const rules: any[] = effective.rules || [];
  const groups = CATEGORIES.map((c) => ({ c, rules: rules.filter((r) => ruleCategory(r.rule_id) === c.key) })).filter((g) => g.rules.length);
  return (
    <>
      <div className="k-toolbar">
        <span className="k-muted" style={{ fontSize: "var(--t-small)" }}>
          {rules.length} rules apply · fired in the last 30 days
        </span>
        <div className="k-toolbar-end">
          <Link href={href("/app/policies/new", { agent: slug })} className="k-btn-primary">
            Add rule for this agent
          </Link>
        </div>
      </div>
      {groups.map(({ c, rules }) => (
        <Card key={c.key} title={categoryLabel(c.key)} flush>
          <table className="k-table">
            <tbody>
              {rules.map((r) => {
                const s = byId[r.rule_id];
                return (
                  <tr key={r.rule_id}>
                    <td>
                      <Link className="k-name" href={`/app/policies/rules/${encodeURIComponent(r.rule_id)}`}>
                        {ruleTitle(r.rule_id)}
                      </Link>
                      {r.source && !String(r.source).startsWith("org:") && <span className="sub">Custom for this agent</span>}
                    </td>
                    <td className="tight"><ActionPill effect={r.effect} /></td>
                    <td className="tight"><ModePill mode={r.enforcement} /></td>
                    <td className="tight">{s ? <Sparkline values={s.series} width={60} /> : null}</td>
                    <td className="num tight">{s ? <Link href={runsHref({ ...f, range: "30d" }, { rule: r.rule_id })}>{num(s.fires)}</Link> : <span className="k-muted">0</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      ))}
    </>
  );
}

async function Activity({ f, outcome }: { f: Filters; outcome?: string }) {
  const qs = new URLSearchParams({ agent: f.agent!, limit: "100", since_days: String(RANGE_DAYS[f.range]) });
  const v = verdictsFor(outcome);
  if (v) qs.set("verdict", v);
  if (outcome === "errors") qs.set("errors", "true");
  const runs = await safeApi<any>(`/api/traces?${qs}`, { traces: [] });
  const chip = (key: string, label: string) => (
    <Link
      key={key}
      className={(outcome || "") === key ? "active" : ""}
      href={href(`/app/agents/${encodeURIComponent(f.agent!)}`, { tab: "activity", outcome: key || undefined, range: f.range === "7d" ? undefined : f.range })}
      scroll={false}
    >
      {label}
    </Link>
  );
  return (
    <>
      <FilterBar>
        <div className="k-seg">
          {chip("", "All")}
          {chip("blocked", "Blocked")}
          {chip("held", "Held")}
          {chip("errors", "Errors")}
        </div>
      </FilterBar>
      <Card flush>
        <RunsTable runs={runs.traces} showAgent={false} />
      </Card>
    </>
  );
}

async function Quality({ slug, posture }: { slug: string; posture: any }) {
  const report = await safeApi<any>(`/api/escalation/report?agent=${encodeURIComponent(slug)}`, null);
  const slos: any[] = posture.slos || [];
  return (
    <>
      {report && (
        <Grid cols={4}>
          <Kpi label="Hand-offs to people" value={num(report.handoffs)} />
          <Kpi label="Missed hand-offs" value={num(report.missed_escalations)} tone={report.missed_escalations ? "bad" : undefined} hint="Conversations that should have reached a person and didn't." />
          <Kpi label="False resolutions" value={num(report.false_resolutions)} hint="Marked resolved when the problem wasn't." />
          <Kpi label="Missed rate" value={pctOf(report.missed_escalations, report.qualified_for_escalation || 0)} />
        </Grid>
      )}
      <Card title="Reliability targets" action={<Link href="/app/test?tab=suites">Tests</Link>} flush>
        {slos.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Measure</th>
                <th className="num">Target</th>
                <th className="num">Actual</th>
                <th className="tight">Status</th>
              </tr>
            </thead>
            <tbody>
              {slos.map((s) => (
                <tr key={s.slo_id || s.scorer}>
                  <td>{s.scorer}</td>
                  <td className="num">{s.target != null ? `${Math.round(s.target * 100)}%` : "—"}</td>
                  <td className="num">{s.attainment != null ? `${Math.round(s.attainment * 100)}%` : "—"}</td>
                  <td className="tight">
                    <Pill tone={s.status === "breached" ? "bad" : s.status === "at_risk" ? "warn" : s.status === "met" ? "ok" : "outline"}>
                      {String(s.status || "no data").replace(/_/g, " ")}
                    </Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty action={<Link href="/app/test?tab=suites" className="k-btn">Set a target</Link>}>No reliability targets.</Empty>
        )}
      </Card>
    </>
  );
}

function Settings({ a, state }: { a: any; state: string }) {
  const action = `/api/agents/${encodeURIComponent(a.slug)}/owner`;
  return (
    <>
      <Card title="Details">
        <form action={action} method="POST" className="k-form">
          <div className="k-field">
            <label htmlFor="s-purpose">Purpose</label>
            <input id="s-purpose" className="k-input" name="purpose" defaultValue={a.purpose || ""} placeholder="Answers billing questions from account history" />
          </div>
          <div className="k-field">
            <label htmlFor="s-owner">Owner</label>
            <input id="s-owner" className="k-input" type="email" name="owner_email" defaultValue={a.owner_email || ""} placeholder="owner@company.com" />
          </div>
          <div className="k-field">
            <label htmlFor="s-team">Team</label>
            <input id="s-team" className="k-input" name="owner_team" defaultValue={a.owner_team || ""} />
          </div>
          <div className="k-field">
            <label htmlFor="s-risk">Risk level</label>
            <select id="s-risk" className="k-select" name="risk_tier" defaultValue={a.risk_tier || "limited"} style={{ width: 160 }}>
              <option value="minimal">Minimal</option>
              <option value="limited">Limited</option>
              <option value="high">High</option>
              <option value="prohibited">Prohibited</option>
            </select>
          </div>
          <div className="k-field">
            <span />
            <span>
              <button type="submit" className="k-btn-primary">Save</button>
            </span>
          </div>
        </form>
      </Card>
      <Card title="Registration" flush>
        <table className="k-table">
          <tbody>
            <tr><td className="muted">Slug</td><td className="k-mono">{a.slug}</td></tr>
            <tr><td className="muted">Registered</td><td>{a.registered ? "Yes" : <Pill tone="bad">No</Pill>}</td></tr>
            <tr><td className="muted">Models</td><td>{a.declared_models?.join(", ") || "—"}</td></tr>
            <tr><td className="muted">Data it handles</td><td>{a.data_classes?.join(", ") || "—"}</td></tr>
            <tr><td className="muted">First seen</td><td>{ago(a.first_seen_at)}</td></tr>
          </tbody>
        </table>
      </Card>
      <Card title="Emergency stop" hint="Pause refuses every call from this agent until resumed. Stop is the stronger incident action.">
        <div className="k-pills" style={{ gap: 8 }}>
          {state === "active" ? <Pill tone="ok">Active</Pill> : <Pill tone="bad">{state}</Pill>}
          <form action={`/api/agents/${encodeURIComponent(a.slug)}/control`} method="POST" className="k-pills" style={{ gap: 8 }}>
            <input type="hidden" name="action" value={state === "active" ? "quarantine" : "resume"} />
            <input className="k-input" name="reason" placeholder="Reason (optional)" style={{ width: 240 }} />
            <button type="submit" className={state === "active" ? "k-btn-danger" : "k-btn"}>{state === "active" ? "Pause" : "Resume"}</button>
          </form>
          {state !== "killed" && (
            <form action={`/api/agents/${encodeURIComponent(a.slug)}/control`} method="POST">
              <input type="hidden" name="action" value="kill" />
              <button type="submit" className="k-btn-danger">Stop</button>
            </form>
          )}
        </div>
      </Card>
    </>
  );
}

async function MapTab({ slug }: { slug: string }) {
  const map = await safeApi<any>(`/api/agents/${encodeURIComponent(slug)}/map`, null);
  return map ? <GuardrailMap map={map} /> : <Card><Empty>The map could not be loaded.</Empty></Card>;
}
