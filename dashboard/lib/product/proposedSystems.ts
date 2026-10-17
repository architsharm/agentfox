/**
 * The Proposed list, grouped into the systems a repo scan found. A multi-agent
 * repository is proposed as one agent per agent, joined by the handoffs its code
 * declares; listing those flat hides which ones belong together, and adding the
 * orchestrator without its sub-agents leaves it handing work to agents nothing governs.
 */

export type ProposedAgent = {
  id: string;
  slug: string;
  name?: string;
  framework?: string | null;
  children?: { slug: string; relation?: string | null }[];
};

export type SystemMember<A extends ProposedAgent = ProposedAgent> = {
  agent: A;
  /** 0 for the system's root, 1 for what it hands work to, and so on. */
  depth: number;
  /** How the parent above hands work to this one; null for the root. */
  relation: string | null;
};

export type ProposedGroup<A extends ProposedAgent = ProposedAgent> = {
  root: A;
  /** The root first, then each agent under the one that hands it work. */
  members: SystemMember<A>[];
};

/**
 * Group proposed agents into systems. An agent no other proposal hands work to is a
 * root; everything it reaches is listed under it, once, under the first parent met. A
 * cycle (agents that hand back to each other) is cut where it closes. A group with one
 * member is an ordinary single proposal.
 */
export function groupProposed<A extends ProposedAgent>(proposed: A[]): ProposedGroup<A>[] {
  const bySlug = new Map(proposed.map((a) => [a.slug, a]));
  const kids = new Map<string, { slug: string; relation: string | null }[]>();
  const hasParent = new Set<string>();
  for (const a of proposed) {
    const list = (a.children || []).filter((c) => bySlug.has(c.slug) && c.slug !== a.slug);
    kids.set(
      a.slug,
      list.map((c) => ({ slug: c.slug, relation: c.relation ?? null })),
    );
    for (const c of list) hasParent.add(c.slug);
  }

  const placed = new Set<string>();
  const groups: ProposedGroup<A>[] = [];
  const walk = (slug: string, depth: number, relation: string | null, into: SystemMember<A>[]) => {
    if (placed.has(slug)) return;
    placed.add(slug);
    into.push({ agent: bySlug.get(slug)!, depth, relation });
    for (const c of kids.get(slug) || []) walk(c.slug, depth + 1, c.relation, into);
  };
  const start = (a: A) => {
    if (placed.has(a.slug)) return;
    const members: SystemMember<A>[] = [];
    walk(a.slug, 0, null, members);
    groups.push({ root: a, members });
  };
  for (const a of proposed) if (!hasParent.has(a.slug)) start(a);
  // Agents reachable only through a cycle: start from the first one met.
  for (const a of proposed) start(a);
  return groups;
}

/** "Hands off", "Used as a tool", ... — how an indented member is reached, in words. */
export function memberRelation(relation: string | null): string {
  switch (relation) {
    case "handoff":
      return "Handed off to";
    case "as_tool":
      return "Used as a tool";
    case "member":
      return "Member";
    case null:
      return "";
    default:
      return "Delegated to";
  }
}
