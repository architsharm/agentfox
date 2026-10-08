import { href } from "@/components/kit";
import { rangeOf, type Outcome, type RangeKey } from "@/lib/product/vocab";

export type Filters = { range: RangeKey; agent?: string; env?: string };

export function filtersFrom(sp: Record<string, string | undefined>): Filters {
  return { range: rangeOf(sp.range), agent: sp.agent || undefined, env: sp.env || undefined };
}

/** Query string for /api/metrics/*. */
export function metricsQs(f: Filters, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams({ range: f.range, ...extra });
  if (f.agent) q.set("agent", f.agent);
  if (f.env) q.set("environment", f.env);
  return q.toString();
}

/** Filters carried from one view to the next, so switching tabs keeps them. */
export function keep(f: Filters): Record<string, string | undefined> {
  return { range: f.range === "7d" ? undefined : f.range, agent: f.agent, env: f.env };
}

export const OBSERVE_TABS = [
  { key: "overview", label: "Overview" },
  { key: "breaks", label: "What breaks" },
  { key: "security", label: "Security" },
  { key: "review", label: "Human review" },
  { key: "cost", label: "Cost & speed" },
  { key: "runs", label: "Runs" },
] as const;

export function observeTabs(f: Filters) {
  return OBSERVE_TABS.map((t) => ({
    key: t.key,
    label: t.label,
    href:
      t.key === "runs"
        ? href("/app/traces", keep(f))
        : href("/app/observe", { ...keep(f), tab: t.key === "overview" ? undefined : t.key }),
  }));
}

const VERDICTS: Record<Outcome, string> = {
  allowed: "allow",
  masked: "redact,mask,tokenize",
  held: "escalate",
  blocked: "block",
};

/** A link to the runs behind any number. */
export function runsHref(
  f: Filters,
  more: { outcome?: Outcome; rule?: string; tool?: string; start?: string; end?: string; errors?: boolean } = {},
): string {
  return href("/app/traces", {
    ...keep(f),
    outcome: more.outcome,
    rule: more.rule,
    tool: more.tool,
    start: more.start,
    end: more.end,
    errors: more.errors ? "1" : undefined,
  });
}

export function verdictsFor(outcome?: string): string | undefined {
  return outcome && outcome in VERDICTS ? VERDICTS[outcome as Outcome] : undefined;
}

export const RANGE_DAYS: Record<RangeKey, number> = { "24h": 1, "7d": 7, "30d": 30, "90d": 90 };
