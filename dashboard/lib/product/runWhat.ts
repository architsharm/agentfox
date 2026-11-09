/**
 * The "What" of an activity row, in words.
 *
 * A run's summary is normally what the person asked. Two things used to leak
 * through instead: an Agents SDK hand-off, whose tool is `transfer_to_faq_agent`
 * and whose output is `{"assistant": "FAQ Agent"}`, shown as raw JSON; and a
 * tool's output, which is also JSON, shown as if it were the request. A hand-off
 * now reads "Handed off to FAQ Agent", and JSON is never the headline.
 */

export function handoffTarget(tool?: string | null): string | null {
  const m = /^transfer_to_(.+)$/.exec(String(tool || ""));
  if (!m) return null;
  return m[1]
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => (w.length <= 3 && w !== "the" ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(" ");
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

export function runWhat(t: any, surfaces: Record<string, string> = {}): string {
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
    const handoffs = tools.map(handoffTarget).filter(Boolean) as string[];
    const rest = tools.filter((x) => !handoffTarget(x));
    const parts = [...rest, ...handoffs.map((h) => `handed off to ${h}`)];
    const text = parts.join(", ");
    return rest.length ? text : text[0].toUpperCase() + text.slice(1);
  }
  const s = (t.surfaces || []).map((x: string) => surfaces[x] || x).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i).join(" · ");
  return s || "Model call";
}
