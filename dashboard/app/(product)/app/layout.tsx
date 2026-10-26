import Link from "next/link";
import { Suspense } from "react";
import { cookies } from "next/headers";
import { SESSION_COOKIE, safeApi } from "@/lib/product/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Logo } from "@/components/product/Logo";
import { AccountMenu } from "@/components/product/AccountMenu";
import { NotificationsBell } from "@/components/product/NotificationsBell";
import { CommandSearch } from "@/components/product/CommandSearch";
import { SideNav } from "@/components/product/SideNav";
import { MobileMenu } from "@/components/product/MobileMenu";
import { TableLabels } from "@/components/product/TableLabels";
import { AppChrome } from "@/components/product/AppChrome";
import { Crumbs } from "@/components/product/Crumbs";
import { WORKSPACE_NAV } from "@/lib/product/nav";
import { MAP_PROJECT_COOKIE, NEW_PROJECT } from "@/lib/product/project";
import { apiBase } from "@/lib/env";
import { TopbarStats } from "@/components/product/TopbarStats";
import { getEdition } from "@/lib/product/edition";

/**
 * The app chrome — sidebar, topbar — for everything under `/app`.
 *
 * This used to live in the ROOT layout, behind `isAppPage`, computed from an
 * `x-pathname` header that middleware.ts sets on every request. It rendered
 * correctly on a full page load and was wrong on every client-side navigation
 * into the app: Next does not re-render a layout that both routes share, so
 * arriving at /app from the marketing site by clicking "Dashboard" reused the
 * root layout's marketing output and the sidebar never appeared. Reloading the
 * same URL rendered the layout fresh and it came back — which is exactly the
 * shape of the bug that was reported.
 *
 * A layout at this path cannot get that wrong. It is mounted by the router only
 * for `/app` and below, so there is no condition to evaluate, nothing to read
 * out of a header, and no way for a shared parent's cached output to answer for
 * a route it does not belong to.
 *
 * `signedIn` is still checked, but only for the topbar: middleware already
 * redirects a signed-out request for a private path to /login, so this is the
 * belt to that braces, not the gate.
 */
/**
 * Destinations that used to be their own sidebar item before the nav was
 * consolidated into tabs — findable by name in search even though the
 * sidebar itself only shows the parent page. Losing a sidebar item is not
 * the same as losing the ability to find the thing by typing its name.
 */
const NAV_SEARCH_ONLY: { label: string; href: string; group: string; feature?: string }[] = [
  { label: "Runs", href: "/app/traces", group: "Observe" },
  { label: "What breaks", href: "/app/observe?tab=breaks", group: "Observe" },
  { label: "Security", href: "/app/observe?tab=security", group: "Observe" },
  { label: "Cost & speed", href: "/app/observe?tab=cost", group: "Observe" },
  { label: "Policy performance", href: "/app/policies?tab=performance", group: "Policies" },
  { label: "Policy library", href: "/app/policies?tab=libraries", group: "Policies" },
  { label: "Suggested changes", href: "/app/policies?tab=changes", group: "Policies" },
  { label: "Detectors", href: "/app/policies?tab=advanced", group: "Policies" },
  { label: "Attack tests", href: "/app/test?tab=attacks", group: "Test" },
  { label: "Test suites", href: "/app/test?tab=suites", group: "Test" },
  { label: "Compliance", href: "/app/compliance", group: "Reports", feature: "compliance" },
  { label: "Threat coverage", href: "/app/coverage", group: "Reports" },
  { label: "Evidence", href: "/app/reports?tab=evidence", group: "Reports", feature: "evidence" },
  { label: "Audit log", href: "/app/reports?tab=audit", group: "Reports" },
  { label: "Connections", href: "/app/start?tab=connect", group: "Settings" },
  { label: "API keys", href: "/app/start?tab=tokens", group: "Settings" },
  { label: "Alerts", href: "/app/settings?tab=alerts", group: "Settings", feature: "monitoring" },
  { label: "Verified sources", href: "/app/sources", group: "Settings" },
  { label: "Data access", href: "/app/entitlement", group: "Settings" },
  { label: "Glossary", href: "/app/glossary", group: "Reference" },
];

const NAV_FLAT: { label: string; href: string; group: string; feature?: string }[] = WORKSPACE_NAV.flatMap(
  ({ group, items }) => items.map(([label, href]) => ({ label, href, group: group || "Home" })),
).concat(NAV_SEARCH_ONLY);
/**
 * The topbar's data: who is signed in and what needs attention. Its own Suspense
 * boundary, because the layout awaiting it held back every page under /app, and
 * its loading state, until both calls had answered.
 */
async function TopbarData() {
  const [me, attention, { features }] = await Promise.all([
    safeApi<any>("/api/me", null),
    safeApi<any>("/api/attention", { items: [], total: 0 }),
    getEdition(),
  ]);
  const nav = NAV_FLAT.filter((n) => !n.feature || features.has(n.feature));
  return (
    <div className="topbar-right">
      {attention?.counts && <TopbarStats counts={attention.counts} />}
      <CommandSearch nav={nav} />
      <NotificationsBell items={attention?.items?.slice(0, 6) || []} total={attention?.total || 0} />
      {me && <AccountMenu email={me.email} workspace={me.workspace} role={me.role} />}
    </div>
  );
}

/**
 * The sidebar, with the projects its switcher offers. In its own Suspense
 * boundary for the same reason as the topbar; until the list answers, the
 * sidebar is already there in the scope the cookie names.
 */
async function SideNavData({ initial }: { initial: string | null }) {
  const { projects } = await safeApi<any>("/api/projects", { projects: [] });
  return <SideNav projects={projects || []} initial={initial} />;
}

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const jar = await cookies();
  const signedIn = Boolean(jar.get(SESSION_COOKIE)?.value);
  const project = jar.get(MAP_PROJECT_COOKIE)?.value || null;

  // AppChrome drops the sidebar and topbar on full-screen routes (onboarding).
  // Adding a project, or having none yet: the same view either way — each page's own
  // empty cards and the connection card. A new signup and "+ Add a project" match.
  const projectCount = signedIn ? ((await safeApi<any>("/api/projects", { projects: [] })).projects ?? []).length : 0;
  const adding = signedIn && (project === NEW_PROJECT || projectCount === 0);
  const newProject = adding ? { server: apiBase(), first: projectCount === 0 } : null;
  return (
    <AppChrome
      newProject={newProject}
      side={
        <nav className="side">
          {/* The mark and the name only. "by Nometria" sat under both of them
              as a block, which put it under the fox rather than under the
              word, and at 11px in a 224px rail it read as a stray caption.
              The parent brand belongs where there is room for it: the public
              footer and the sign-in page both carry it. */}
          <Link href="/app" className="brand" aria-label="Overview">
            <Logo size={26} />
            <span className="brand-text">
              <span className="brand-name">
                <span className="brand-path">~/</span> agentfox
              </span>
              <span className="brand-sub">guard your agents</span>
            </span>
          </Link>
          <MobileMenu />
          <TableLabels />
          <Suspense fallback={<SideNav projects={[]} initial={project} />}>
            {signedIn ? <SideNavData initial={project} /> : <SideNav projects={[]} initial={null} />}
          </Suspense>
          <div className="side-foot">
            <span className="live-dot">live</span>
            <ThemeToggle />
          </div>
        </nav>
      }
      topbar={
        signedIn && (
          <div className="topbar">
            <Crumbs />
            <Suspense fallback={<CommandSearch nav={NAV_FLAT} />}>
              <TopbarData />
            </Suspense>
          </div>
        )
      }
    >
      {children}
    </AppChrome>
  );
}
