/**
 * The sidebar, in each of its two scopes (see lib/product/project.ts).
 *
 * All projects is the workspace: is anything wrong (Home), what is happening
 * (Observe), what is broken (Issues), which projects (Projects), what is allowed
 * (Policies), what needs me (Approvals), does it hold up (Test), show others
 * (Reports). One project is that project's pages only: its canvas (the map of
 * its guardrails, and everything about it when nothing is selected), its traffic,
 * what it may do, its issues and approvals, its settings. The workspace pages
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

const SETUP: NavGroup = {
  group: "Setup",
  items: [
    ["Get started", "/app/start"],
    [
      "Settings",
      "/app/settings",
      ["/app/start?tab=connect", "/app/start?tab=tokens", "/app/sources", "/app/entitlement"],
    ],
  ],
};

export const WORKSPACE_NAV: NavGroup[] = [
  {
    group: "",
    items: [
      ["Home", "/app"],
      ["Projects", "/app/projects"],
      ["Observe", "/app/observe", ["/app/traces"]],
      ["Issues", "/app/findings"],
      ["Policies", "/app/policies"],
      ["Approvals", "/app/approvals"],
      ["Test", "/app/test", ["/app/evals"]],
      ["Reports", "/app/reports", ["/app/compliance", "/app/coverage"]],
    ],
  },
  SETUP,
];

export function projectNav(slug: string): NavGroup[] {
  const q = `agent=${encodeURIComponent(slug)}`;
  return [
    {
      group: "",
      items: [
        ["Canvas", projectHref(slug), [`/app/projects/${encodeURIComponent(slug)}?view=canvas`], "canvas"],
        ["Activity", projectHref(slug, "activity"), [`/app/observe?${q}`, `/app/traces?${q}`], "/app/observe"],
        ["Access", projectHref(slug, "access"), [], "/app/entitlement"],
        ["Issues", `/app/findings?${q}`],
        ["Approvals", `/app/approvals?${q}`],
        ["Settings", projectHref(slug, "settings"), [], "/app/settings"],
      ],
    },
    { group: "Workspace", items: [["Get started", "/app/start"], ["Workspace settings", "/app/settings", SETUP.items[1][2]]] },
  ];
}
