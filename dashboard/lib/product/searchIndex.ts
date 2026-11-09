/**
 * What Cmd-K searches besides page names: agents, tools, rules and open issues.
 *
 * Built once per open of the palette from list endpoints the app already calls
 * (`/api/agents`, `/api/tools`, `/api/policies?full=1`, `/api/findings?status=open`),
 * through `app/api/search/route.ts`, and matched in the browser, so typing stays
 * instant. It used to find page names only, so "refund" or a tool's name found
 * nothing.
 */

export type SearchItem = { label: string; href: string; group: string; sub?: string };

const LIMIT = 300;

export function buildIndex(data: {
  agents?: any[];
  tools?: any[];
  policies?: any[];
  findings?: any[];
}): SearchItem[] {
  const out: SearchItem[] = [];
  for (const a of data.agents || []) {
    if (!a?.slug) continue;
    out.push({ label: a.name || a.slug, sub: a.slug, href: `/app/projects/${encodeURIComponent(a.slug)}`, group: "Agent" });
  }
  for (const t of data.tools || []) {
    if (!t?.key) continue;
    out.push({ label: t.name || t.key, sub: t.key, href: `/app/tools`, group: "Tool" });
  }
  const seen = new Set<string>();
  for (const p of data.policies || []) {
    const compiled = p?.live_compiled?.rules ? p.live_compiled : p?.compiled || {};
    for (const r of compiled.rules || []) {
      if (!r?.id || seen.has(r.id)) continue;
      seen.add(r.id);
      out.push({
        label: r.description || r.id,
        sub: r.id,
        href: `/app/policies/rules/${encodeURIComponent(r.id)}`,
        group: "Rule",
      });
    }
  }
  for (const f of data.findings || []) {
    if (!f?.id) continue;
    out.push({
      label: f.title || f.id,
      sub: [f.severity, f.agent_slug || f.agent].filter(Boolean).join(" · ") || undefined,
      href: `/app/findings/${encodeURIComponent(f.id)}`,
      group: "Issue",
    });
  }
  return out.slice(0, LIMIT * 4);
}

/** Items whose label, id or group contain every word typed, best (label prefix) first. */
export function match(items: SearchItem[], query: string, limit = 40): SearchItem[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return items.slice(0, limit);
  const scored: { item: SearchItem; score: number }[] = [];
  for (const item of items) {
    const hay = `${item.label} ${item.sub || ""} ${item.group}`.toLowerCase();
    if (!words.every((w) => hay.includes(w))) continue;
    const label = item.label.toLowerCase();
    const score = label.startsWith(words[0]) ? 0 : label.includes(words[0]) ? 1 : 2;
    scored.push({ item, score });
  }
  return scored.sort((a, b) => a.score - b.score).slice(0, limit).map((s) => s.item);
}
