import Link from "next/link";
import { cookies } from "next/headers";
import { SESSION_COOKIE, safeApi } from "@/lib/api";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Wordmark } from "@/components/Logo";
import { AccountMenu } from "@/components/AccountMenu";
import { NotificationsBell } from "@/components/NotificationsBell";
import { CommandSearch } from "@/components/CommandSearch";
import { SideNav, type NavItem } from "@/components/SideNav";
import { TopbarStats } from "@/components/TopbarStats";

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
const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "",
    items: [
      ["Overview", "/app"],
      ["Start here", "/app/start"],
    ],
  },
  {
    group: "Discover",
    items: [
      ["Agents", "/app/agents"],
      ["Verified sources", "/app/sources"],
    ],
  },
  {
    group: "Monitor",
    items: [
      ["Findings", "/app/findings"],
      ["Traces", "/app/traces"],
    ],
  },
  {
    group: "Test",
    items: [
      ["Evaluation", "/app/evals"],
    ],
  },
  {
    group: "Govern",
    items: [
      ["Policies", "/app/policies"],
      ["Access control", "/app/entitlement"],
      ["Approvals", "/app/approvals"],
      ["Compliance", "/app/compliance"],
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
  { label: "Connect GitHub", href: "/app/start?tab=connect", group: "Start here" },
  { label: "Connect a hosted API", href: "/app/start?tab=connect", group: "Start here" },
  { label: "API tokens", href: "/app/start?tab=tokens", group: "Start here" },
  { label: "Guardrail tuning", href: "/app/policies?tab=guardrails", group: "Policies" },
  { label: "Judgment posture", href: "/app/policies?tab=judgment", group: "Policies" },
  { label: "Egress", href: "/app/policies?tab=judgment", group: "Policies" },
  { label: "Escalation", href: "/app/approvals?tab=escalation", group: "Approvals" },
  { label: "Board view", href: "/app/compliance?tab=board", group: "Compliance" },
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
