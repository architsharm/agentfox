import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { post, safeApi } from "@/lib/product/api";
import { ActionPill, BarList, Card, Empty, Grid, Header, Kpi, ModePill, Pill, Tabs, ago, href, num } from "@/components/kit";
import { FilterBar } from "@/components/kit/FilterBar";
import { RunsTable } from "@/components/kit/RunsTable";
import { CustomRule } from "@/components/product/policies/CustomRule";
import { RuleTests } from "@/components/product/policies/RuleTests";
import { RuleTuner, type RuleScope } from "@/components/product/policies/RuleTuner";
import { RuleChecks } from "@/components/product/policies/RuleChecks";
import { checksFor, type CheckInfo } from "@/lib/product/checks";
import { RANGE_DAYS, metricsQs, runsHref } from "@/lib/product/observe";
import { loadRules, ruleMode, type RuleInfo } from "@/lib/product/rules";
import { ensureRange } from "@/lib/product/range";
import { RangeProvider } from "@/components/kit/RangeContext";
import { categoryLabel, rangeOf, ruleCategory, ruleTitle } from "@/lib/product/vocab";

export const metadata: Metadata = appPageMetadata("Rule");
export const dynamic = "force-dynamic";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "examples", label: "Hits" },
  { key: "tests", label: "Tests" },
  { key: "tune", label: "Tune" },
  { key: "history", label: "History" },
];

type SP = Record<string, string | undefined>;

export default async function RulePage({ params, searchParams }: { params: Promise<{ ruleId: string }>; searchParams: Promise<SP> }) {
  const { ruleId: raw } = await params;
  const ruleId = decodeURIComponent(raw);
  const sp = await searchParams;
  // A rule written in the workspace's own words can also be edited and deleted here.
  const tabs = ruleId.startsWith("custom.") ? [TABS[0], { key: "edit", label: "Edit" }, ...TABS.slice(1)] : TABS;
  const tab = tabs.some((t) => t.key === sp.tab) ? sp.tab! : "overview";
  if (tab === "overview" || tab === "examples") await ensureRange(`/app/policies/rules/${encodeURIComponent(ruleId)}`, sp);
  const range = rangeOf(sp.range);

  const custom = ruleId.startsWith("custom.");
  const [{ packs, rules }, stats, customRules] = await Promise.all([
    loadRules(),
    safeApi<any>(`/api/metrics/rules?${metricsQs({ range })}`, { rules: [] }),
    custom ? safeApi<any>("/api/custom-rules", { rules: [] }) : Promise.resolve({ rules: [] }),
  ]);
  const own = (customRules.rules || []).find((r: any) => r.rule_id === ruleId);
  const rule = rules.find((r) => r.rule_id === ruleId);
  const s = (stats.rules || []).find((r: any) => r.rule_id === ruleId);
  const mode = rule ? ruleMode(rule) : null;
  const tabHref = (k: string) => href(`/app/policies/rules/${encodeURIComponent(ruleId)}`, { tab: k === "overview" ? undefined : k, range: sp.range, agent: k === "tune" ? sp.agent : undefined });

  return (
    <RangeProvider range={sp.range}>
    <>
      <Header
        back={{ href: "/app/policies", label: "Policies" }}
        title={ruleTitle(ruleId, rule?.description)}
        hint={ruleId.startsWith("custom.") ? undefined : rule?.description}
        meta={
          <>
            {rule && <ActionPill effect={rule.effect} />}
            <ModePill mode={mode} />
            <Pill tone="outline">{categoryLabel(ruleCategory(ruleId))}</Pill>
          </>
        }
        actions={
          <Link className="k-btn" href={tabHref("tune")}>
            Change
          </Link>
        }
      />
      <Tabs items={tabs.map((t) => ({ ...t, href: tabHref(t.key) }))} active={tab} />

      {tab === "overview" && (
        <>
          <FilterBar />
          <Grid cols={4}>
            <Kpi label="Hits" value={num(s?.fires || 0)} spark={s?.series} href={runsHref({ range }, { rule: ruleId })} />
            <Kpi label="Stopped" value={num(s?.enforced || 0)} />
            <Kpi label="Would have stopped" value={num(s?.watched || 0)} hint="Hits while the rule was only watching." />
            <Kpi label="Last hit" value={s ? ago(s.last_fired) : "Never"} />
          </Grid>
          <Grid cols={2}>
            <Card title="By agent">
              <BarList rows={Object.entries(s?.agents || {}).map(([k, v]) => ({ key: k, label: k, value: v as number, href: `/app/projects/${encodeURIComponent(k)}` }))} empty="No hits" />
            </Card>
            <Card title="By tool">
              <BarList rows={Object.entries(s?.tools || {}).map(([k, v]) => ({ key: k, label: k, value: v as number, href: runsHref({ range }, { rule: ruleId, tool: k }) }))} empty="Not tool-specific" />
            </Card>
          </Grid>
          <Card title="In libraries" flush>
            {rule ? (
              <table className="k-table">
                <tbody>
                  {rule.packs.map((p) => (
                    <tr key={p.key}>
                      <td><Link className="k-name" href={`/app/policies/${encodeURIComponent(p.key)}`}>{p.name}</Link></td>
                      <td className="tight"><ActionPill effect={p.effect} /></td>
                      <td className="tight">{p.enabled ? <ModePill mode={p.mode} /> : <Pill tone="outline">Off</Pill>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>Not in any applied library.</Empty>
            )}
          </Card>
        </>
      )}

      {tab === "examples" && <Examples ruleId={ruleId} range={range} />}

      {tab === "edit" && (
        <Card>{own ? <CustomRule initial={own} /> : <Empty>This rule's definition could not be found.</Empty>}</Card>
      )}

      {tab === "tests" && (
        <Card>
          {rule ? <Tests ruleId={ruleId} pack={rule.packs[0]?.key} agents={Object.keys(s?.agents || {})} /> : <Empty>Not in any applied library.</Empty>}
        </Card>
      )}

      {tab === "tune" && rule?.finds ? <CheckedBy finds={rule.finds} agent={sp.agent} /> : null}
      {tab === "tune" && (
        <Card title="What this rule does">
          {rule ? <Tune ruleId={ruleId} packs={rule.packs} exact={own ? own.kind !== "topic" : false} agent={sp.agent} /> : <Empty>Not in any applied library.</Empty>}
        </Card>
      )}

      {tab === "history" && (
        <Card flush>
          {rule ? (
            <table className="k-table">
              <tbody>
                {packs
                  .filter((p) => rule.packs.some((x) => x.key === p.key))
                  .flatMap((p) => p.versions.map((v: any) => ({ ...v, pack: p, live: v.version === p.boundVersion })))
                  .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
                  .map((v) => (
                    <tr key={v.id}>
                      <td>
                        <span className="k-name">{v.notes || `Version ${v.version}`}</span>
                        <span className="sub">{v.pack.name}</span>
                      </td>
                      <td className="tight">{v.live ? <Pill tone="ok">Live</Pill> : <Pill tone="outline">v{v.version}</Pill>}</td>
                      <td className="tight muted">{v.author}</td>
                      <td className="tight muted">{ago(v.created_at)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          ) : (
            <Empty>No history.</Empty>
          )}
        </Card>
      )}
    </>
    </RangeProvider>
  );
}

/** The tuner, with every agent (sub-agents nested) for "Only some agents". */
async function Tune({ ruleId, packs, exact, agent }: { ruleId: string; packs: RuleInfo["packs"]; exact: boolean; agent?: string }) {
  const workspace = packs.filter((p) => !p.key.startsWith("agent."));
  const scopes: Record<string, RuleScope> = {};
  await Promise.all(
    workspace.map(async (p) => {
      const out = await safeApi<RuleScope | null>(`/api/policies/${encodeURIComponent(p.key)}/rules/${encodeURIComponent(ruleId)}/agents`, null);
      if (out) scopes[p.key] = out;
    }),
  );
  return <RuleTuner ruleId={ruleId} packs={packs} exact={exact} scopes={scopes} agent={agent} />;
}

async function Examples({ ruleId, range }: { ruleId: string; range: keyof typeof RANGE_DAYS }) {
  const runs = await safeApi<any>(`/api/traces?rule=${encodeURIComponent(ruleId)}&since_days=${RANGE_DAYS[range]}&limit=50`, { traces: [] });
  return (
    <>
      <FilterBar />
      <Card flush>
        <RunsTable runs={runs.traces} />
      </Card>
    </>
  );
}

async function Tests({ ruleId, pack, agents }: { ruleId: string; pack?: string; agents: string[] }) {
  const [checked, all] = await Promise.all([
    pack
      ? post<any>(`/api/rules/${encodeURIComponent(ruleId)}/examples/check`, { policy: pack }).catch(() => ({ results: [] }))
      : Promise.resolve({ results: [] }),
    safeApi<any>("/api/agents", { agents: [] }),
  ]);
  const slugs = Array.from(new Set([...agents, ...(all.agents || []).filter((a: any) => a.status !== "draft").map((a: any) => a.slug)]));
  return <RuleTests ruleId={ruleId} results={checked.results || []} agents={slugs} />;
}

/**
 * The checks that can fire this rule: any check that reports what it looks for. Regex,
 * ML and LLM judges alike; a check is switched on per agent, so with an agent chosen
 * they can be turned on and off here.
 */
async function CheckedBy({ finds, agent }: { finds: string; agent?: string }) {
  const [detectors, map] = await Promise.all([
    safeApi<any>("/api/detectors", { detectors: [] }),
    agent ? safeApi<any>(`/api/agents/${encodeURIComponent(agent)}/map`, null) : Promise.resolve(null),
  ]);
  const catalog: CheckInfo[] = (detectors.detectors || []).map((d: any) => ({
    key: d.key,
    label: d.label || "",
    source: d.source,
    surfaces: d.surfaces || [],
    available: Boolean(d.available),
    finds: d.finds || "",
  }));
  const on: string[] = Array.from(new Set((map?.stages || []).flatMap((st: any) => st.detectors || [])));
  return (
    <Card
      title="Checked by"
      hint={agent ? `Checks on for ${agent} that can fire this rule. A check is on or off for the whole agent.` : "Checks that can fire this rule. Choose an agent below to turn them on or off for it."}
    >
      <RuleChecks checks={checksFor(finds, catalog)} on={on} agent={agent} />
    </Card>
  );
}

