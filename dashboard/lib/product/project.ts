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

/** The views of one project, in the order the page offers them. */
export const PROJECT_VIEWS = [
  { key: "canvas", label: "Canvas" },
  { key: "activity", label: "Activity" },
  { key: "access", label: "Access" },
  { key: "features", label: "Features" },
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
