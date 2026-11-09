/**
 * The sidebar, in each of its two scopes (see lib/product/project.ts).
 *
 * All projects is the workspace: which agents (Agents), what is allowed
 * (Policies), what needs me (Approvals), what is broken (Issues), does it hold up
 * (Testing), what happened (Activity), show others (Reports), and how it is set up
 * (Settings, whose Detection tab holds the protection levels every project gets).
 * One project is that project's pages only: its canvas (the map of its guardrails,
 * and everything about it when nothing is selected), what it may do (Access), its
 * issues and approvals, its traffic, its settings. The workspace pages stay one
 * click away, under All projects in the switcher.
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
  [
    "/app/sources",
    "/app/entitlement",
    "/app/features",
    "/app/guardrails",
  ],
];

/**
 * Guardrails is everything: Agents (each project's map) is home and the place to set
 * things up; Policies, Approvals, Issues and Testing are the ways back in to what
 * needs a decision; Activity is the record behind all of it, for troubleshooting
 * (its tabs include Tools, Models, Sessions and Events); Reports is what you show
 * others (Compliance, Threat coverage, Evidence and the audit log are its tabs).
 */
export const WORKSPACE_NAV: NavGroup[] = [
  {
    group: "Guardrails",
    items: [
      ["Agents", "/app/map", ["/app/projects", "/app/onboarding", "/app/welcome"], "/app/projects"],
      ["Policies", "/app/policies"],
      ["Approvals", "/app/approvals"],
      ["Issues", "/app/findings"],
      ["Testing", "/app/test"],
      [
        "Activity",
        "/app/traces",
        ["/app/observe", "/app/tools", "/app/models", "/app/events", "/app/sessions", "/app/escalation/conversations"],
      ],
      ["Reports", "/app/reports", ["/app/compliance", "/app/coverage", "/app/board"]],
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
        // "Access", not "Policies": it opens the agent's Access tab, and Policies is the
        // workspace's rules list.
        ["Access", projectHref(slug, "access"), [projectHref(slug, "features")], "/app/entitlement"],
        ["Approvals", `/app/approvals?${q}`],
        ["Issues", `/app/findings?${q}`],
        ["Activity", `/app/traces?${q}`, [projectHref(slug, "activity"), `/app/observe?${q}`], "/app/traces"],
      ],
    },
    { group: "", items: [["Settings", projectHref(slug, "settings"), [], "/app/settings"]] },
  ];
}
