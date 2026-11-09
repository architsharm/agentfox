/**
 * Projects: what the API calls an agent, as the dashboard presents it.
 *
 * The dashboard works in one of two scopes. A project scope is one project and
 * everything about it: its canvas, its activity, its issues and approvals. The
 * all-projects scope is the workspace: every project's issues, the policies they
 * share, the reports. The scope a person last chose is kept in a cookie, so the
 * sidebar can show the matching set of pages on any page they open; the URL of a
 * project page sets it too (see middleware.ts), so a link to a project lands in
 * that project's scope.
 *
 * Kept free of server-only imports: middleware, server components and the
 * switcher in the sidebar all read it.
 */

/** The cookie holding the selected project's slug. Absent or empty: all projects. */
export const PROJECT_COOKIE = "agentfox_project";

/**
 * The project the Map shows: a repository `agentfox init` mapped, with every agent in
 * it (GET /api/projects). One at a time, never several together. Chosen in the
 * sidebar's switcher; absent, the most recently mapped one.
 */
export const MAP_PROJECT_COOKIE = "agentfox_map_project";

/**
 * The project being added: chosen from "+ Add a project", not connected yet. Every
 * page then shows its own empty state and the connection card, never another
 * project's data, until `agentfox init` reports in or another project is chosen.
 */
export const NEW_PROJECT = "__new__";

/** Member states that are not an agent someone added: a scan's proposal, an agent seen running unregistered. */
const NOT_ADDED = new Set(["draft", "shadow"]);

/**
 * The project shown when none is chosen: of the projects with an agent someone added
 * (not a scan's proposal, not a shadow agent seen running unregistered), the one with
 * the most recent traffic; with no traffic anywhere, the first of them in the API's
 * order. Falls back to the first project. Takes GET /api/projects rows.
 */
export function defaultProject<T extends { project: string; last_seen_at?: string | null; members?: { status?: string }[] }>(projects: T[]): T | undefined {
  const added = projects.filter((p) => (p.members ?? []).some((m) => m.status && !NOT_ADDED.has(m.status)));
  const seen = added.filter((p) => p.last_seen_at).sort((a, b) => String(b.last_seen_at).localeCompare(String(a.last_seen_at)));
  return seen[0] ?? added[0] ?? projects[0];
}

/** Has anyone added an agent yet (one that is not a proposal or a shadow)? Takes GET /api/projects rows. */
export function hasAddedAgent(projects: { members?: { status?: string }[] }[]): boolean {
  const gone = new Set([...NOT_ADDED, "removed", "rejected"]);
  return projects.some((p) => (p.members ?? []).some((m) => m.status && !gone.has(m.status)));
}

/** The views of one project, in the order the page offers them. */
export const PROJECT_VIEWS = [
  { key: "canvas", label: "Canvas" },
  { key: "activity", label: "Activity" },
  { key: "access", label: "Access" },
  { key: "features", label: "Features" },
  { key: "controls", label: "Controls" },
  { key: "settings", label: "Settings" },
] as const;

export type ProjectView = (typeof PROJECT_VIEWS)[number]["key"];

/**
 * The agent page's seven tabs, and where each one's content lives now. The map,
 * its rules and the overview are the canvas; everything about traffic is activity.
 * Kept so a bookmarked `?tab=` still opens the right view.
 */
const VIEW_FOR_TAB: Record<string, ProjectView> = {
  overview: "canvas",
  map: "canvas",
  rules: "activity",
  permissions: "activity",
  activity: "activity",
  quality: "activity",
  access: "access",
  features: "features",
  controls: "controls",
  breaker: "controls",
  settings: "settings",
  registration: "settings",
};

/** The view a project URL asks for: `?view=`, else an old `?tab=`, else the canvas. */
export function projectView(sp: { view?: string; tab?: string }): ProjectView {
  if (sp.view && PROJECT_VIEWS.some((v) => v.key === sp.view)) return sp.view as ProjectView;
  if (sp.tab && VIEW_FOR_TAB[sp.tab]) return VIEW_FOR_TAB[sp.tab];
  return "canvas";
}

/** A project's page, at a view. The canvas is the default and has no `?view=`. */
export function projectHref(slug: string, view: ProjectView = "canvas", extra: Record<string, string | undefined> = {}): string {
  const q = new URLSearchParams();
  if (view !== "canvas") q.set("view", view);
  for (const [k, v] of Object.entries(extra)) if (v) q.set(k, v);
  const qs = q.toString();
  return `/app/projects/${encodeURIComponent(slug)}${qs ? `?${qs}` : ""}`;
}

/** The project slug a `/app/projects/<slug>…` path names, if any. */
export function projectInPath(pathname: string): string | null {
  const m = pathname.match(/^\/app\/projects\/([^/?#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** How long the chosen scope is remembered: a year, like any other preference. */
export const PROJECT_COOKIE_AGE = 60 * 60 * 24 * 365;

/** A member of a project, as GET /api/projects lists it. */
export type ProjectMember = { slug: string; name?: string; repo?: string | null; status?: string };

/** A row of GET /api/projects: one system (a root and what it hands work to). */
export type ProjectRow = {
  project: string;
  /** Set by `switcherOptions`: the repository the row stands for, or null. */
  repo?: string | null;
  agents: number;
  slugs?: string[];
  members?: ProjectMember[];
  name?: string;
  repos?: string[];
  last_seen_at?: string | null;
};

/**
 * What the switcher offers: one row per repository `agentfox init` mapped (its
 * systems together, as the map draws them), and each system no repository holds on
 * its own. The API lists systems, so a repository of three independent agents was
 * three identical "mono · 1 agent" rows while its map showed 3 agents. Counted the
 * way the map counts: each agent once, only agents someone added or proposed (not
 * one disconnected).
 */
export function switcherOptions(projects: ProjectRow[]): ProjectRow[] {
  const out = new Map<string, ProjectRow>();
  for (const p of projects) {
    // A system belongs to its root's repository: the map of that repository draws it.
    const repo = p.members?.find((m) => m.slug === p.project)?.repo ?? (p.repos?.length === 1 ? p.repos[0] : null);
    const key = repo ?? p.project;
    const prev = out.get(key);
    const members = [...(prev?.members ?? []), ...(p.members ?? [])].filter(
      (m, i, all) => all.findIndex((x) => x.slug === m.slug) === i,
    );
    const seen = [prev?.last_seen_at, p.last_seen_at].filter(Boolean).sort().pop() ?? null;
    out.set(key, {
      ...(prev ?? p),
      project: key,
      repo,
      name: repo ?? p.name,
      repos: [...new Set([...(prev?.repos ?? []), ...(p.repos ?? [])])].sort(),
      members,
      slugs: members.map((m) => m.slug),
      agents: members.filter((m) => !["removed", "rejected"].includes(m.status ?? "")).length,
      last_seen_at: seen,
    });
  }
  return [...out.values()];
}

/**
 * The switcher option a page is scoped to: the one `asked` (a URL's project) or the
 * cookie names (an option's key, a system's root or any agent in it), else the
 * default. Every page that scopes to "the project" goes through this, so the switcher,
 * the map and Policies count the same agents: Policies used to look the cookie up
 * among systems, miss the repository key, and fall back to one system ("4 agents"
 * beside the switcher's "11 agents").
 */
export function chosenOption(projects: ProjectRow[], cookie?: string | null, asked?: string | null): ProjectRow | undefined {
  const options = switcherOptions(projects);
  const find = (key?: string | null) => (key ? options.find((o) => o.project === key || o.slugs?.includes(key)) : undefined);
  return find(asked) ?? find(cookie) ?? defaultProject(options);
}

/** The agents disconnecting an option takes off the dashboard: its members from its repository (or, with none, from none). */
export function disconnectedBy(option: ProjectRow): ProjectMember[] {
  const repo = option.repo !== undefined ? option.repo : option.repos?.length === 1 ? option.repos[0] : null;
  return (option.members ?? []).filter((m) => (m.repo ?? null) === repo && !["removed", "rejected"].includes(m.status ?? ""));
}

/**
 * The agent the map opens a project on: the one with the most recent traffic, an added
 * agent before a proposal; with no traffic, the root (the map's first agent). Takes the
 * project map's agents and GET /api/agents rows (for `last_seen_at`).
 */
export function openingAgent(
  mapAgents: { slug: string; status?: string; depth?: number }[],
  agents: { slug: string; last_seen_at?: string | null }[],
): string | undefined {
  const seen = new Map(agents.map((a) => [a.slug, a.last_seen_at ?? ""]));
  const ranked = [...mapAgents].sort(
    (a, b) =>
      Number(NOT_ADDED.has(a.status ?? "")) - Number(NOT_ADDED.has(b.status ?? "")) ||
      String(seen.get(b.slug) ?? "").localeCompare(String(seen.get(a.slug) ?? "")) ||
      (a.depth ?? 0) - (b.depth ?? 0),
  );
  return ranked[0]?.slug;
}
