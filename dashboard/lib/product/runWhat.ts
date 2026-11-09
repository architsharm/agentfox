/**
 * The "What" of an activity row, in words.
 *
 * A run's summary is normally what the person asked. Two things used to leak
 * through instead: an Agents SDK hand-off, whose tool is `transfer_to_faq_agent`
 * and whose output is `{"assistant": "FAQ Agent"}`, shown as raw JSON; and a
 * tool's output, which is also JSON, shown as if it were the request. A hand-off
 * now reads "Handed off to FAQ Agent", and JSON is never the headline.
 */

/**
 * The registry key for a name, as `core/naming.py` `slug` makes it: `RestaurantScout`,
 * `restaurant_scout` and "Restaurant scout" are all `restaurant-scout`.
 */
export function slugOf(value: string): string {
  const words = value.trim().replace(/(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/g, "-");
  return words.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
}

/** A code name in words: `restaurant_scout` -> "Restaurant Scout", `faq_agent` -> "FAQ Agent". */
function humanise(code: string): string {
  return code
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => (w.length <= 3 && w !== "the" ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(" ");
}

export function handoffTarget(tool?: string | null, names?: Map<string, string>): string | null {
  const m = /^transfer_to_(.+)$/.exec(String(tool || ""));
  if (!m) return null;
  // The agent it hands to, by the name people gave it, when it is one of theirs.
  const named = names?.get(slugOf(m[1])) || names?.get(m[1]);
  // A display name that is itself a code name (`agentfox init` keeps the name as the
  // code wrote it) reads as words too.
  if (named) return /^[A-Za-z0-9]+(_[A-Za-z0-9]+)+$/.test(named) ? humanise(named) : named;
  return humanise(m[1]);
}

function looksLikeJson(s: string): boolean {
  const t = s.trim();
  return (t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"));
}

/** The hand-off target named in an Agents SDK hand-off output, if that is what this is. */
function handoffFromOutput(s: string): string | null {
  try {
    const v = JSON.parse(s);
    if (v && typeof v === "object" && !Array.isArray(v) && typeof v.assistant === "string" && Object.keys(v).length === 1) return v.assistant;
  } catch {
    // Not JSON after all.
  }
  return null;
}

export function runWhat(t: any, surfaces: Record<string, string> = {}, names?: Map<string, string>): string {
  const summary = typeof t.summary === "string" ? t.summary.trim() : "";
  const tools: string[] = Array.isArray(t.tools) ? t.tools : [];
  if (summary && looksLikeJson(summary)) {
    const to = handoffFromOutput(summary);
    if (to) return `Handed off to ${to}`;
  } else if (summary) {
    return summary;
  }
  if (typeof t.intent === "string" && t.intent.trim() && !looksLikeJson(t.intent)) return t.intent.trim();
  if (tools.length) {
    const handoffs = tools.map((x) => handoffTarget(x, names)).filter(Boolean) as string[];
    const rest = tools.filter((x) => !handoffTarget(x));
    const parts = [...rest, ...handoffs.map((h) => `handed off to ${h}`)];
    const text = parts.join(", ");
    return rest.length ? text : text[0].toUpperCase() + text.slice(1);
  }
  const s = (t.surfaces || []).map((x: string) => surfaces[x] || x).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i).join(" · ");
  return s || "Model call";
}

/**
 * A run page's title: what the person asked in its turn (`trace.asked`, recorded by
 * the gateway from `agentfox.input`), else what the run did in words. A tool call's
 * page used to be titled with the tool's name ("transfer_to_restaurant_scout").
 */
export function runTitle(t: any, decisions: any[] = [], surfaces: Record<string, string> = {}, names?: Map<string, string>): string {
  const asked = typeof t?.asked === "string" ? t.asked.replace(/\s+/g, " ").trim() : "";
  if (asked) return asked.length > 120 ? `${asked.slice(0, 119).trimEnd()}…` : asked;
  if (typeof t?.intent === "string" && t.intent.trim() && !looksLikeJson(t.intent)) return t.intent.trim();
  const tools = Array.from(new Set(decisions.map((d) => d?.tool).filter(Boolean))) as string[];
  if (tools.length) {
    const handoffs = tools.map((x) => handoffTarget(x, names)).filter(Boolean) as string[];
    const rest = tools.filter((x) => !handoffTarget(x));
    const parts = [...(rest.length ? [`Called ${rest.join(", ")}`] : []), ...handoffs.map((h) => `handed off to ${h}`)];
    const text = parts.join(", ");
    return text[0].toUpperCase() + text.slice(1);
  }
  const s = Array.from(new Set(decisions.map((d) => surfaces[d?.surface] || d?.surface).filter(Boolean)));
  return s.length ? s.join(" · ") : "Run";
}

/**
 * The line under a turn's "What": how many runs it folds and the tools it used,
 * hand-offs in words ("3 steps · file_read · handed off to FAQ Agent").
 */
export function runSteps(t: any, names?: Map<string, string>): string {
  // When the tools already are the headline (nothing asked), only the count is new.
  const what = runWhat(t, {}, names);
  const tools: string[] = Array.isArray(t.tools) && !t.tools.some((x: string) => what.includes(handoffTarget(x, names) || x)) ? t.tools : [];
  const runs = Number(t.runs) || 1;
  const parts: string[] = [];
  if (runs > 1) parts.push(`${runs} steps`);
  const rest = tools.filter((x) => !handoffTarget(x));
  const handoffs = tools.map((x) => handoffTarget(x, names)).filter(Boolean) as string[];
  if (rest.length) parts.push(rest.length > 3 ? `${rest.slice(0, 3).join(", ")} +${rest.length - 3}` : rest.join(", "));
  for (const h of handoffs) parts.push(`handed off to ${h}`);
  return parts.join(" · ");
}
