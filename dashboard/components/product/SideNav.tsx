"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { NavIcon } from "@/components/product/NavIcons";

/** The dashboard's own URL, which is also every other row's prefix. */
const APP_ROOT = "/app";

/** Label, href, and any other pages (path, or path?tab=key) the row stands for. */
export type NavItem = [label: string, href: string, also?: string[]];

type Pattern = { path: string; tab: string | null };

function parse(href: string): Pattern {
  const [path, query] = href.split("?");
  return { path, tab: query ? new URLSearchParams(query).get("tab") : null };
}

/**
 * The active-link highlight is computed on the client: `usePathname()` follows the
 * router on every kind of navigation, where a server-computed highlight stuck on
 * the page you had just left after browser back/forward.
 *
 * A row matches every page in `[href, ...also]`. A pattern with a `?tab=` matches
 * only that tab; a bare path matches its subtree, unless another row claims the
 * open tab of that same path — so "Get started" (/app/start) and "Settings"
 * (/app/start?tab=connect, among others) never light up together. `/app` is the
 * prefix of everything, so it only ever matches exactly.
 */
export function SideNav({
  nav,
}: {
  nav: { group: string; items: NavItem[] }[];
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const currentTab = searchParams.get("tab");
  const patterns = (item: NavItem) => [item[1], ...(item[2] || [])].map(parse);
  const tabClaims = nav.flatMap(({ items }) => items.flatMap(patterns)).filter((p) => p.tab);

  const matches = ({ path, tab }: Pattern) => {
    const pathMatches =
      path === APP_ROOT ? pathname === APP_ROOT : pathname === path || pathname.startsWith(`${path}/`);
    if (!pathMatches) return false;
    if (tab) return currentTab === tab;
    return !(currentTab && tabClaims.some((c) => c.path === path && c.tab === currentTab));
  };

  return (
    <>
      {nav.map(({ group, items }) => (
        <div key={group || "root"}>
          {group && <div className="group">{group}</div>}
          {items.map((item) => {
            const [label, href] = item;
            return (
              <Link
                key={href}
                href={href}
                className={patterns(item).some(matches) ? "active" : undefined}
              >
                <NavIcon href={href} />
                <span>{label}</span>
              </Link>
            );
          })}
        </div>
      ))}
    </>
  );
}
