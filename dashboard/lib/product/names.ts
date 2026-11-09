/**
 * Agents by the name people gave them, not by their slug.
 *
 * Issue titles, approval rows and activity rows are written by the gateway with the
 * agent's slug in them ("payments-ops tried to…", "Identity agent:hr-screening is
 * stale"), because the slug is what the gateway has at hand. On screen the agent
 * already has a display name everywhere else, so these helpers swap it in.
 */

export type AgentLike = { slug?: string | null; name?: string | null };

/** slug → display name, for the agents that have one different from the slug. */
export function agentNames(agents: AgentLike[] | null | undefined): Map<string, string> {
  const m = new Map<string, string>();
  for (const a of agents || []) {
    if (a?.slug && a.name && a.name.trim() && a.name !== a.slug) m.set(a.slug, a.name.trim());
  }
  return m;
}

/** The display name for a slug, or the slug itself. */
export function agentName(names: Map<string, string>, slug?: string | null): string {
  if (!slug) return "";
  return names.get(slug) || slug;
}

function escape(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The same text with every agent slug in it replaced by that agent's name:
 * "agent:hr-screening", "'hr-screening'" and a bare "hr-screening" all become
 * "HR Screening". Longest slugs first, so "support" never eats "support-triage".
 */
export function withAgentNames(text: string | null | undefined, names: Map<string, string>): string {
  let out = String(text ?? "");
  const slugs = [...names.keys()].sort((a, b) => b.length - a.length);
  for (const slug of slugs) {
    const name = names.get(slug)!;
    const s = escape(slug);
    out = out
      .replace(new RegExp(`agent:${s}(?![\\w-])`, "g"), name)
      .replace(new RegExp(`'${s}'`, "g"), name)
      .replace(new RegExp(`(?<![\\w.:/-])${s}(?![\\w-]|\\.\\w)`, "g"), name);
  }
  return out;
}
