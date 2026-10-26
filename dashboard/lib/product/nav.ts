/**
 * The sidebar, in each of its two scopes (see lib/product/project.ts).
 *
 * All projects is the workspace: is anything wrong (Home), what is happening
 * (Observe), what is broken (Issues), which projects (Projects), what is allowed
 * (Policies), which switches are on (Features), what needs me (Approvals), does it hold up (Test), show others
 * (Reports). One project is that project's pages only: its canvas (the map of
 * its guardrails, and everything about it when nothing is selected), its traffic,
 * what it may do, which features it changed, its issues and approvals, its settings. The workspace pages
 * stay one click away, under All projects in the switcher.
 *
 * A row lists the other pages it stands for, so it stays lit on all of them, and
 * may name the icon it shows when its href is not an icon's key.
 *
 * Plain data and functions: the server layout reads it for search, the client
 * sidebar for its rows.
 */
import { projectHref } from "@/lib/product/project";

/** Label, href, other pages (path, or path?key=value) the row stands for, icon. */
export type NavItem = [label: string, href: string, also?: string[], icon?: string];
export type NavGroup = { group: string; items: NavItem[] };

const SETTINGS: NavItem = [
  "Settings",
  "/app/settings",
  ["/app/start", "/app/start?tab=connect", "/app/start?tab=tokens", "/app/sources", "/app/entitlement", "/app/onboarding"],
];

/**
 * Guardrails is everything: Agents (each project's map) is home and the place to set
 * things up; Policies, Features, Approvals, Issues and Testing are the ways back in to
 * what needs a decision; Traces is the record behind all of it, for troubleshooting.
 * Insights is how it is going across the workspace: Monitoring (security, what
 * breaks, cost and speed) and Reports (compliance, coverage, evidence, audit).
 */
export const WORKSPACE_NAV: NavGroup[] = [
  {
    group: "Guardrails",
    items: [
      ["Agents", "/app/map", ["/app/projects"], "/app/projects"],
      ["Policies", "/app/policies"],
      ["Features", "/app/features"],
      ["Approvals", "/app/approvals"],
      ["Issues", "/app/findings"],
      ["Testing", "/app/test", ["/app/evals"]],
      ["Traces", "/app/traces", ["/app/events", "/app/sessions", "/app/escalation/conversations"]],
    ],
  },
  {
    group: "Insights",
    items: [
      ["Monitoring", "/app/observe"],
      ["Reports", "/app/reports", ["/app/compliance", "/app/coverage"]],
    ],
  },
  { group: "", items: [SETTINGS] },
];

export function projectNav(slug: string): NavGroup[] {
  const q = `agent=${encodeURIComponent(slug)}`;
  return [
    {
      group: "Guardrails",
      items: [
        ["Agents", projectHref(slug), [`/app/projects/${encodeURIComponent(slug)}?view=canvas`], "/app/projects"],
        ["Policies", projectHref(slug, "access"), [projectHref(slug, "features")], "/app/policies"],
        ["Approvals", `/app/approvals?${q}`],
        ["Issues", `/app/findings?${q}`],
        ["Traces", `/app/traces?${q}`, [projectHref(slug, "activity"), `/app/observe?${q}`], "/app/traces"],
      ],
    },
    { group: "", items: [["Settings", projectHref(slug, "settings"), [], "/app/settings"]] },
  ];
}
