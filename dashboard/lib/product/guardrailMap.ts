/**
 * The guardrail map's data: types, what colour a step or tool shows, and how a long
 * tool list is grouped and filtered. Kept apart from the drawing so it can be tested.
 */

export type MapRule = {
  id: string;
  description: string;
  effect: string;
  mode: string;
  level: string;
  message: string;
  hits: number;
  enabled?: boolean;
  /** This agent has its own copy of the rule. */
  own?: boolean;
  /** The pack a change for this agent is made against. */
  policy?: string;
  /** The workspace rule lets an agent loosen it. */
  overridable?: boolean;
  /** Broader copies still in force beside a tightened one. */
  also?: { effect: string; mode: string }[];
  workspace?: { effect: string; enabled: boolean };
};
export type Stats = { total?: number; allowed?: number; blocked?: number; held?: number; masked?: number };
export type Stage = { key: string; title: string; surfaces: string[]; detectors: string[]; rules: MapRule[]; stats: Stats };
export type Permission = "allowed" | "ask" | "not_granted";
export type MapTool = {
  key: string;
  name: string;
  impact: string | null;
  permission: Permission;
  limits: Record<string, any>;
  rules: MapRule[];
  ladders: { key: string; name: string; mode: string; field: string | null }[];
  stats: Stats;
  /** Where the tool is known from: its code, a grant, calls seen. */
  sources?: ("code" | "granted" | "seen")[];
  grant?: { id: string; key: string; max_taint: string; actions: string[] } | null;
};
export type AgentMap = {
  agent: { slug: string; name: string };
  window_days: number;
  stages: Stage[];
  everywhere: MapRule[];
  tools: MapTool[];
  subagents: { slug: string; calls: number }[];
};

// --- tone ------------------------------------------------------------------------

export type Tone = "on" | "watch" | "off";

/** A rule stops something when it is on, enforcing, and does more than record. */
export function enforces(r: MapRule): boolean {
  if (r.enabled === false) return false;
  if (r.mode === "enforce" && r.effect !== "allow") return true;
  return (r.also || []).some((a) => a.mode === "enforce" && a.effect !== "allow");
}

export function counts(rules: MapRule[]) {
  const live = rules.filter((r) => r.enabled !== false);
  const enforcing = live.filter(enforces).length;
  return { enforcing, watching: live.length - enforcing };
}

/** Enforcing: something here stops traffic. Watching: checks or rules only record. */
export function stageTone(rules: MapRule[], detectors: string[] = []): Tone {
  const c = counts(rules);
  if (c.enforcing) return "on";
  if (c.watching || detectors.length) return "watch";
  return "off";
}

export function toolTone(t: MapTool): Tone {
  const c = counts(t.rules);
  if (c.enforcing || t.ladders.some((l) => l.mode === "enforce")) return "on";
  if (c.watching || t.ladders.length) return "watch";
  return "off";
}

export const TONE_LABEL: Record<Tone, string> = { on: "Enforcing", watch: "Watching only", off: "Nothing set" };

// --- rule control ------------------------------------------------------------------

export type RuleSetting = "block" | "escalate" | "allow" | "off";

export const RULE_SETTINGS: { key: RuleSetting; label: string; title: string }[] = [
  { key: "block", label: "Block", title: "Block" },
  { key: "escalate", label: "Ask", title: "Ask a person" },
  { key: "allow", label: "Watch", title: "Watch only: record, do not stop" },
  { key: "off", label: "Off", title: "Off for this agent" },
];

/** Which control a rule shows as chosen; null for an action the control does not offer. */
export function ruleSetting(r: MapRule): RuleSetting | null {
  if (r.enabled === false) return "off";
  if (r.effect === "block" || r.effect === "escalate" || r.effect === "allow") return r.effect;
  return null;
}

/** The body for `POST /api/policies/{key}/rules/{id}/scope` that sets this rule for one agent. */
export function ruleChange(slug: string, to: RuleSetting): Record<string, unknown> {
  if (to === "off") return { agents: [slug], enabled: false };
  return { agents: [slug], enabled: true, effect: to };
}

// --- permission control -----------------------------------------------------------

export const PERMISSION: Record<Permission, { label: string; short: string; tone: string }> = {
  allowed: { label: "Allowed", short: "Allow", tone: "ok" },
  ask: { label: "Asks a person", short: "Ask a person", tone: "held" },
  not_granted: { label: "Not allowed", short: "Not allowed", tone: "bad" },
};

/**
 * The access call that gives a tool this permission. Allowing or asking writes the
 * tool's own grant (keeping its limits); "not allowed" removes its grant. A tool
 * reached only through a pattern grant cannot be removed alone: null.
 */
export function permissionCall(slug: string, t: MapTool, to: Permission): { url: string; method: string; body?: unknown } | null {
  const base = `/api/agents/${encodeURIComponent(slug)}/access`;
  if (to === "not_granted") {
    if (!t.grant) return null;
    if (t.grant.key !== t.key) return null;
    return { url: `${base}/${encodeURIComponent(t.grant.id)}`, method: "DELETE" };
  }
  const own = t.grant && t.grant.key === t.key ? t.grant : null;
  return {
    url: base,
    method: "POST",
    body: {
      tool_key: t.key,
      requires_approval: to === "ask",
      max_taint: own?.max_taint || "user",
      constraints: own ? t.limits || {} : {},
      ...(own ? { actions: own.actions } : {}),
    },
  };
}

// --- grouping ----------------------------------------------------------------------

export type GroupBy = "impact" | "permission" | "source" | "prefix";

export const GROUP_BY: { key: GroupBy; label: string }[] = [
  { key: "impact", label: "Risk" },
  { key: "permission", label: "Access" },
  { key: "source", label: "Source" },
  { key: "prefix", label: "Server or prefix" },
];

const IMPACT_GROUPS: [string, string][] = [
  ["irreversible", "Irreversible"],
  ["high_impact", "High impact"],
  ["write", "Writes"],
  ["read", "Read only"],
  ["", "Risk not set"],
];
const PERMISSION_GROUPS: [Permission, string][] = [
  ["not_granted", "Not allowed"],
  ["ask", "Asks a person"],
  ["allowed", "Allowed"],
];
const SOURCE_GROUPS: [string, string][] = [
  ["seen", "Called"],
  ["granted", "Granted, not called"],
  ["code", "In code only"],
];

/** `mcp__github__create_issue` → github; `crm.lookup` → crm; no separator → none. */
export function prefixOf(key: string): string {
  if (key.includes("__")) {
    const parts = key.split("__").filter(Boolean);
    return (parts[0] === "mcp" && parts.length > 2 ? parts[1] : parts[0]) || "";
  }
  const m = key.match(/^([^.:/]+)[.:/]/);
  return m ? m[1] : "";
}

function sourceOf(t: MapTool): string {
  const s = t.sources || [];
  return s.includes("seen") ? "seen" : s.includes("granted") ? "granted" : "code";
}

export type ToolGroup = { key: string; label: string; tools: MapTool[] };

export function groupTools(tools: MapTool[], by: GroupBy): ToolGroup[] {
  if (by === "prefix") {
    const groups = new Map<string, MapTool[]>();
    for (const t of tools) {
      const p = prefixOf(t.key);
      groups.set(p, [...(groups.get(p) || []), t]);
    }
    // Biggest first; tools without a prefix last.
    return [...groups.entries()]
      .sort(([a, x], [b, y]) => Number(a === "") - Number(b === "") || y.length - x.length || a.localeCompare(b))
      .map(([key, ts]) => ({ key: `prefix:${key}`, label: key || "No prefix", tools: ts }));
  }
  const order = by === "impact" ? IMPACT_GROUPS : by === "permission" ? PERMISSION_GROUPS : SOURCE_GROUPS;
  const of = (t: MapTool) => (by === "impact" ? t.impact || "" : by === "permission" ? t.permission : sourceOf(t));
  const known = new Set(order.map(([k]) => k));
  return order
    .map(([key, label]) => ({
      key: `${by}:${key}`,
      label,
      tools: tools.filter((t) => of(t) === key || (key === "" && !known.has(of(t)))),
    }))
    .filter((g) => g.tools.length);
}

export type ToolFilter = "all" | Permission | "called" | "rules";

export const TOOL_FILTERS: { key: ToolFilter; label: string }[] = [
  { key: "all", label: "All tools" },
  { key: "allowed", label: "Allowed" },
  { key: "ask", label: "Asks a person" },
  { key: "not_granted", label: "Not allowed" },
  { key: "called", label: "Called" },
  { key: "rules", label: "Has rules" },
];

export function filterTools(tools: MapTool[], query: string, filter: ToolFilter): MapTool[] {
  const q = query.trim().toLowerCase();
  return tools.filter((t) => {
    if (q && !t.key.toLowerCase().includes(q) && !(t.name || "").toLowerCase().includes(q)) return false;
    if (filter === "all") return true;
    if (filter === "called") return Boolean(t.stats.total);
    if (filter === "rules") return t.rules.length + t.ladders.length > 0;
    return t.permission === filter;
  });
}

/** Up to this many tools are drawn one by one; more are drawn as groups. */
export const DRAW_EACH = 12;
/** At most this many tools of an opened group are drawn; the rest are in the list. */
export const DRAW_OPEN = 12;
/** At most this many groups are drawn; the rest are in the list. */
export const DRAW_GROUPS = 12;

export function groupSummary(tools: MapTool[]) {
  const by = (p: Permission) => tools.filter((t) => t.permission === p).length;
  const calls = tools.reduce((n, t) => n + (t.stats.total || 0), 0);
  const stopped = tools.reduce((n, t) => n + (t.stats.blocked || 0) + (t.stats.held || 0) + (t.stats.masked || 0), 0);
  const tones = tools.map(toolTone);
  const tone: Tone = tones.includes("on") ? "on" : tones.includes("watch") ? "watch" : "off";
  return { allowed: by("allowed"), ask: by("ask"), denied: by("not_granted"), calls, stopped, tone };
}
