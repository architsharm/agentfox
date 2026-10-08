import Link from "next/link";
import { cookies } from "next/headers";
import { SESSION_COOKIE, safeApi } from "@/lib/product/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Wordmark } from "@/components/product/Logo";
import { AccountMenu } from "@/components/product/AccountMenu";
import { NotificationsBell } from "@/components/product/NotificationsBell";
import { CommandSearch } from "@/components/product/CommandSearch";
import { SideNav, type NavItem } from "@/components/product/SideNav";
import { TopbarStats } from "@/components/product/TopbarStats";

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
 * The sidebar is the customer's jobs, in the order they reach for them: is
 * anything wrong (Home), what is happening (Observe), what is broken (Issues),
 * which agent (Agents), what is allowed (Policies), what needs me (Approvals),
 * does it hold up (Test), show others (Reports). Setup sits at the bottom.
 *
 * A row lists the other pages it stands for, so it stays lit on all of them.
 */
const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "",
    items: [
      ["Home", "/app"],
      ["Observe", "/app/observe", ["/app/traces"]],
      ["Issues", "/app/findings"],
      ["Agents", "/app/agents"],
      ["Policies", "/app/policies"],
      ["Approvals", "/app/approvals"],
      ["Test", "/app/test", ["/app/evals"]],
      ["Reports", "/app/reports", ["/app/compliance", "/app/coverage"]],
    ],
  },
  {
    group: "Setup",
    items: [
      ["Get started", "/app/start"],
      [
        "Settings",
        "/app/settings",
        ["/app/start?tab=connect", "/app/start?tab=tokens", "/app/sources", "/app/entitlement"],
      ],
    ],
  },
];

/**
 * Destinations that used to be their own sidebar item before the nav was
 * consolidated into tabs — findable by name in search even though the
 * sidebar itself only shows the parent page. Losing a sidebar item is not
 * the same as losing the ability to find the thing by typing its name.
 */
const NAV_SEARCH_ONLY: { label: string; href: string; group: string }[] = [
  { label: "Runs", href: "/app/traces", group: "Observe" },
  { label: "What breaks", href: "/app/observe?tab=breaks", group: "Observe" },
  { label: "Security", href: "/app/observe?tab=security", group: "Observe" },
  { label: "Cost & speed", href: "/app/observe?tab=cost", group: "Observe" },
  { label: "Policy performance", href: "/app/policies?tab=performance", group: "Policies" },
  { label: "Policy library", href: "/app/policies?tab=library", group: "Policies" },
  { label: "Suggested changes", href: "/app/policies?tab=changes", group: "Policies" },
  { label: "Detectors", href: "/app/policies?tab=advanced", group: "Policies" },
  { label: "Attack tests", href: "/app/test?tab=attacks", group: "Test" },
  { label: "Test suites", href: "/app/test?tab=suites", group: "Test" },
  { label: "Compliance", href: "/app/compliance", group: "Reports" },
  { label: "Threat coverage", href: "/app/coverage", group: "Reports" },
  { label: "Evidence", href: "/app/reports?tab=evidence", group: "Reports" },
  { label: "Audit log", href: "/app/reports?tab=audit", group: "Reports" },
  { label: "Connect GitHub", href: "/app/start?tab=connect", group: "Settings" },
  { label: "API keys", href: "/app/start?tab=tokens", group: "Settings" },
  { label: "Alerts", href: "/app/settings?tab=alerts", group: "Settings" },
  { label: "Verified sources", href: "/app/sources", group: "Settings" },
  { label: "Data access", href: "/app/entitlement", group: "Settings" },
  { label: "Glossary", href: "/app/glossary", group: "Reference" },
];

const NAV_FLAT = NAV.flatMap(({ group, items }) =>
  items.map(([label, href]) => ({ label, href, group: group || "Home" })),
).concat(NAV_SEARCH_ONLY);
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const signedIn = Boolean((await cookies()).get(SESSION_COOKIE)?.value);

  let me: any = null;
  let attention: any = null;
  if (signedIn) {
    [me, attention] = await Promise.all([
      safeApi("/api/me", null),
      safeApi("/api/attention", { items: [], total: 0 }),
    ]);
  }

  return (
    <div className="shell">
      <nav className="side">
        {/* The mark and the name only. "by Nometria" sat under both of them
            as a block, which put it under the fox rather than under the
            word, and at 11px in a 224px rail it read as a stray caption.
            The parent brand belongs where there is room for it: the public
            footer and the sign-in page both carry it. */}
        <Link href="/app" className="brand" aria-label="Overview">
          <Wordmark />
        </Link>
        <SideNav nav={NAV} />
        <ThemeToggle />
      </nav>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {signedIn && (
          <div className="topbar">
            {attention?.counts && <TopbarStats counts={attention.counts} />}
            <CommandSearch nav={NAV_FLAT} />
            <NotificationsBell items={attention?.items?.slice(0, 6) || []} total={attention?.total || 0} />
            {me && <AccountMenu email={me.email} workspace={me.workspace} role={me.role} />}
          </div>
        )}
        <main>{children}</main>
      </div>
    </div>
  );
}
