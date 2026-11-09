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
  /** content: fed by checks (regex, ML, LLM); action: about a tool call; run: the run as a whole. */
  kind?: "content" | "action" | "run";
  /** What a content rule looks for (`PII`, `INJECTION.JAILBREAK`): checks that report it feed the rule. */
  finds?: string;
  /** How sure a check must be before a content rule acts. */
  minScore?: number | null;
  /** What a rule that isn't about content looks at, in plain words. */
  about?: string;
  /** The library it comes from ("Baseline runtime guardrails", "Basic guardrails"…). */
  library?: string;
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
/** How a parent hands work to a sub-agent, when its code says (a repo scan read it). */
export type Relation = "handoff" | "as_tool" | "delegates" | "member";
/** One end of a delegation: a sub-agent this agent hands work to, or a parent that hands it work. */
export type MapLink = {
  slug: string;
  name?: string;
  calls: number;
  /** Read from the code by a repo scan. */
  declared?: boolean;
  /** Seen in traffic. */
  seen?: boolean;
  relation?: Relation | string | null;
};
export type AgentMap = {
  agent: { slug: string; name: string; framework?: string | null; models?: string[] };
  window_days: number;
  stages: Stage[];
  everywhere: MapRule[];
  tools: MapTool[];
  subagents: MapLink[];
  /** The agents that hand this one work. */
  parents?: MapLink[];
};

// --- sub-agents --------------------------------------------------------------------

/** What the arrow to a sub-agent means, in words. A crew's members are a crew; other teams are a team. */
export function relationLabel(relation: MapLink["relation"], framework?: string | null): string {
  switch (relation) {
    case "handoff":
      return "Hands off to";
    case "as_tool":
      return "Used as a tool";
    case "member":
      return framework === "CrewAI" ? "Crew member" : "Team member";
    default:
      return "Delegates to";
  }
}

/** The same relation seen from the sub-agent's side. */
export function parentLabel(relation: MapLink["relation"]): string {
  switch (relation) {
    case "as_tool":
      return "Used as a tool by";
    case "member":
      return "Member of";
    case "handoff":
      return "Handed off from";
    default:
      return "Called by";
  }
}

/** "3 calls", or for a delegation only the code knows about yet, "From code · no calls yet". */
export function linkActivity(s: MapLink): string {
  if (s.calls > 0) return `${s.calls} ${s.calls === 1 ? "call" : "calls"}`;
  return s.declared ? "From code · no calls yet" : "No calls yet";
}

/** At most this many sub-agents are drawn; the rest are summed up in one node. */
export const DRAW_SUBAGENTS = 6;

/** The sub-agents drawn, busiest first, and how many are left out. */
export function drawnSubagents(subs: MapLink[], max = DRAW_SUBAGENTS): { shown: MapLink[]; rest: number } {
  const ranked = [...subs].sort((a, b) => b.calls - a.calls || a.slug.localeCompare(b.slug));
  const shown = ranked.length > max ? ranked.slice(0, max - 1) : ranked;
  return { shown, rest: ranked.length - shown.length };
}

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

export type RuleSetting = "block" | "escalate" | "redact" | "allow" | "off";

export const RULE_SETTINGS: { key: RuleSetting; label: string; title: string }[] = [
  { key: "block", label: "Block", title: "Block" },
  { key: "escalate", label: "Ask", title: "Ask a person" },
  { key: "redact", label: "Hide", title: "Hide what was found and let the rest through" },
  { key: "allow", label: "Watch", title: "Watch only: record, do not stop" },
  { key: "off", label: "Off", title: "Off for this agent" },
];

/** The actions a rule can take: hiding only makes sense for content. */
export function settingsFor(r: MapRule) {
  return r.kind === "content" ? RULE_SETTINGS : RULE_SETTINGS.filter((o) => o.key !== "redact");
}

/** Which control a rule shows as chosen; null for an action the control does not offer. */
export function ruleSetting(r: MapRule): RuleSetting | null {
  if (r.enabled === false) return "off";
  if (r.effect === "block" || r.effect === "escalate" || r.effect === "allow") return r.effect;
  if (r.effect === "redact" || r.effect === "mask" || r.effect === "tokenize") return "redact";
  return null;
}

/** Whether a check feeds a content rule: it reports the kind of finding the rule looks for. */
export function feeds(check: { finds?: string }, rule: MapRule): boolean {
  if (rule.kind !== "content" || !check.finds || !rule.finds) return false;
  return rule.finds.split(".")[0] === check.finds;
}

/** The body for `POST /api/policies/{key}/rules/{id}/scope` that sets this rule for one agent. */
export function ruleChange(slug: string, to: RuleSetting): Record<string, unknown> {
  if (to === "off") return { agents: [slug], enabled: false };
  return { agents: [slug], enabled: true, effect: to };
}

/**
 * Whether a rule's chosen setting is live. A rule in a pack that only watches records
 * what it would do and stops nothing, so its "Block" is not a block yet. Null when
 * live (or when the setting is Watch or Off, which are the same either way); else the
 * note the control shows under it.
 */
export function watchingNote(r: MapRule): string | null {
  const s = ruleSetting(r);
  if (s === null || s === "allow" || s === "off") return null;
  if (enforces(r)) return null;
  const from = r.library ? ` ${r.library} is` : " Its library is";
  const verb = { block: "block", escalate: "ask a person", redact: "hide", allow: "", off: "" }[s];
  return `Watching:${from} only recording, so this rule would ${verb} but stops nothing yet.`;
}

/** The colour a rule's action reads in: stopping is red, holding amber, hiding blue; watching and allowing are quiet. */
export type ActionTone = "block" | "held" | "hide" | "quiet";
export function actionTone(r: Pick<MapRule, "effect" | "mode" | "enabled">): ActionTone {
  if (r.enabled === false || r.effect === "allow" || r.mode !== "enforce") return "quiet";
  if (r.effect === "block") return "block";
  if (r.effect === "escalate") return "held";
  return "hide";
}

/** What a content rule looks for, in words: `INJECTION.JAILBREAK` → "prompt injection". */
const FINDS: Record<string, string> = {
  INJECTION: "prompt injection",
  PII: "personal data",
  SECRET: "a secret",
  SECRETS: "a secret",
  SAFETY: "harmful content",
  CODE: "insecure code",
  GROUNDING: "an unsupported answer",
  SCHEMA: "a malformed reply",
  TOXICITY: "toxic language",
  TOPIC: "the topic",
};
export function findsLabel(finds?: string): string {
  const head = (finds || "").split(".")[0].toUpperCase();
  return FINDS[head] || (head ? head.toLowerCase().replace(/_/g, " ") : "a finding");
}

/**
 * A content rule's threshold as a sentence: "Block if prompt injection ≥ 0.7".
 * Null for a rule that tests no detection score.
 */
export function thresholdText(r: Pick<MapRule, "effect" | "finds" | "minScore">): string | null {
  if (r.minScore == null) return null;
  const verb: Record<string, string> = { block: "Block", escalate: "Ask a person", redact: "Hide it", mask: "Hide it", tokenize: "Hide it", allow: "Record" };
  return `${verb[r.effect] ?? "Act"} if ${findsLabel(r.finds)} ≥ ${r.minScore}`;
}

/**
 * A 409 from the scope route, in words a person can act on. The gateway's message
 * names the rule id and the pack key; this names the library and says what to do.
 */
export function looseningText(r: Pick<MapRule, "library">, agentName: string): string {
  const lib = r.library || "its library";
  return `${lib} doesn't let one agent loosen this rule, so it can't be relaxed for ${agentName} alone.`;
}

// --- limits ------------------------------------------------------------------------

const CURRENCY: Record<string, string> = { USD: "$", EUR: "€", GBP: "£" };

/**
 * A tool's argument limits as words, never JSON: `{amount: {lt: 1000}, currency: {in:
 * ["USD"]}}` → ["amount under $1,000", "currency USD only"]. An amount takes the
 * currency symbol only when another limit pins the currency to one value.
 */
export function limitsText(limits: Record<string, any> | null | undefined): string[] {
  const entries = Object.entries(limits || {});
  const pinned = entries
    .map(([, spec]) => (spec && typeof spec === "object" && Array.isArray(spec.in) && spec.in.length === 1 ? String(spec.in[0]).toUpperCase() : null))
    .find((c) => c && CURRENCY[c]);
  const money = (arg: string, v: unknown) =>
    typeof v === "number" ? (pinned && /amount|price|total|value|sum|cost/i.test(arg) ? `${CURRENCY[pinned]}${v.toLocaleString("en-US")}` : v.toLocaleString("en-US")) : String(v);
  const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : [String(v)]);
  const or = (xs: string[]) => (xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} or ${xs[xs.length - 1]}`);
  return entries.map(([arg, spec]) => {
    if (!spec || typeof spec !== "object" || Array.isArray(spec)) return `${arg} exactly ${list(spec).join(", ")}`;
    const parts = Object.entries(spec).map(([op, v]) => {
      switch (op) {
        case "lt":
          return `under ${money(arg, v)}`;
        case "lte":
        case "max":
          return `at most ${money(arg, v)}`;
        case "gt":
          return `over ${money(arg, v)}`;
        case "gte":
        case "min":
          return `at least ${money(arg, v)}`;
        case "eq":
          return `exactly ${money(arg, v)}`;
        case "ne":
          return `anything but ${money(arg, v)}`;
        case "in":
          return list(v).length === 1 ? `${list(v)[0]} only` : `${or(list(v))}`;
        case "not_in":
          return `not ${or(list(v))}`;
        case "contains":
          return `containing “${v}”`;
        case "matches":
          return `matching ${v}`;
        default:
          return `${op} ${list(v).join(", ")}`;
      }
    });
    return `${arg} ${parts.join(" and ")}`;
  });
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

/**
 * The canvas shows a project's shape before its detail. Up to this many tools are
 * drawn one by one; with more, they are one "Tools" node until it is expanded, and
 * then one node per group.
 */
export const DRAW_EACH = 6;
/** At most this many tools of an opened group are drawn; "+N more" opens the rest in the inspector. */
export const DRAW_OPEN = 6;
/** At most this many groups are drawn; "+N more" opens the whole list in the inspector. */
export const DRAW_GROUPS = 6;

export type Drawn = { collapsed: boolean; tools: MapTool[]; groups: ToolGroup[] | null; open: ToolGroup | null };

/** What the canvas draws for these tools. A single group is drawn open: there is nothing to choose. */
export function drawTools(visible: MapTool[], by: GroupBy, expanded: boolean, openKey: string | null): Drawn {
  if (visible.length <= DRAW_EACH) return { collapsed: false, tools: visible, groups: null, open: null };
  if (!expanded) return { collapsed: true, tools: [], groups: null, open: null };
  const groups = groupTools(visible, by);
  const open = groups.length === 1 ? groups[0] : groups.find((g) => g.key === openKey) || null;
  return { collapsed: false, tools: [], groups, open };
}

export function groupSummary(tools: MapTool[]) {
  const by = (p: Permission) => tools.filter((t) => t.permission === p).length;
  const calls = tools.reduce((n, t) => n + (t.stats.total || 0), 0);
  const stopped = tools.reduce((n, t) => n + (t.stats.blocked || 0) + (t.stats.held || 0) + (t.stats.masked || 0), 0);
  const tones = tools.map(toolTone);
  const tone: Tone = tones.includes("on") ? "on" : tones.includes("watch") ? "watch" : "off";
  return { allowed: by("allowed"), ask: by("ask"), denied: by("not_granted"), calls, stopped, tone };
}
