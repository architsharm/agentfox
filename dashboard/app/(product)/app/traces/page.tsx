import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { api, safeApi, apiErrorProps } from "@/lib/product/api";
import { ApiDown } from "@/components/ui";
import { Card, Header, Tabs, href, when } from "@/components/kit";
import { FilterBar } from "@/components/kit/FilterBar";
import { RunsTable } from "@/components/kit/RunsTable";
import { RANGE_DAYS, filtersFrom, keep, metricsQs, observeTabs, verdictsFor } from "@/lib/product/observe";
import { ensureRange } from "@/lib/product/range";
import { ruleTitle } from "@/lib/product/vocab";

export const metadata: Metadata = appPageMetadata("Runs");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

const OUTCOME_CHIPS = [
  { key: "", label: "All" },
  { key: "blocked", label: "Blocked" },
  { key: "held", label: "Held" },
  { key: "masked", label: "Masked" },
  { key: "errors", label: "Errors" },
];

export default async function Runs({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  await ensureRange("/app/traces", sp);
  const f = filtersFrom(sp);
  const errorsOnly = sp.errors === "1" || sp.outcome === "errors";

  const qs = new URLSearchParams({ limit: "200", since_days: String(RANGE_DAYS[f.range]) });
  if (f.agent) qs.set("agent", f.agent);
  if (f.env) qs.set("environment", f.env);
  const verdict = verdictsFor(sp.outcome) || sp.verdict;
  if (verdict) qs.set("verdict", verdict);
  if (sp.rule) qs.set("rule", sp.rule);
  if (sp.tool) qs.set("tool", sp.tool);
  if (sp.start) qs.set("start", sp.start);
  if (sp.end) qs.set("end", sp.end);
  if (sp.entity_type) qs.set("entity_type", sp.entity_type);
  if (errorsOnly) qs.set("errors", "true");

  let data: any;
  const [agents, envs] = await Promise.all([
    safeApi<any>("/api/agents", { agents: [] }),
    safeApi<any>(`/api/metrics/breakdown?${metricsQs({ range: "90d" }, { dim: "environment" })}`, { rows: [] }),
  ]);
  try {
    data = await api(`/api/traces?${qs}`);
  } catch (e: any) {
    return (
      <>
        <Header title="Observe" />
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const base = { ...keep(f), rule: sp.rule, tool: sp.tool, start: sp.start, end: sp.end };
  const activeOutcome = errorsOnly ? "errors" : sp.outcome || "";
  // Drill-down filters arrive from a chart or a list; each can be cleared on its own.
  const chips: { label: string; clear: Record<string, string | undefined> }[] = [];
  if (sp.rule) chips.push({ label: ruleTitle(sp.rule), clear: { rule: undefined } });
  if (sp.tool) chips.push({ label: sp.tool, clear: { tool: undefined } });
  if (sp.start || sp.end) chips.push({ label: `${when(sp.start)} – ${when(sp.end)}`, clear: { start: undefined, end: undefined } });

  return (
    <>
      <Header title="Observe" />
      <Tabs items={observeTabs(f)} active="runs" />
      <FilterBar
        agents={(agents.agents || []).map((a: any) => ({ slug: a.slug, name: a.name }))}
        environments={(envs.rows || []).map((r: any) => r.key)}
      >
        <div className="k-seg" role="group" aria-label="Outcome">
          {OUTCOME_CHIPS.map((c) => (
            <Link
              key={c.key || "all"}
              href={href("/app/traces", { ...base, outcome: c.key && c.key !== "errors" ? c.key : undefined, errors: c.key === "errors" ? "1" : undefined })}
              className={activeOutcome === c.key ? "active" : ""}
              scroll={false}
            >
              {c.label}
            </Link>
          ))}
        </div>
      </FilterBar>
      {chips.length > 0 && (
        <div className="chipbar">
          {chips.map((c) => (
            <Link key={c.label} className="chip active" href={href("/app/traces", { ...base, outcome: sp.outcome, errors: sp.errors, ...c.clear })}>
              {c.label} ×
            </Link>
          ))}
        </div>
      )}
      <Card flush>
        <RunsTable runs={data.traces} />
      </Card>
    </>
  );
}
