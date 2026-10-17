"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { NavIcon } from "@/components/product/NavIcons";
import { ProjectSwitcher, type ProjectOption } from "@/components/product/ProjectSwitcher";
import { WORKSPACE_NAV, projectNav, type NavGroup, type NavItem } from "@/lib/product/nav";
import { useProjectScope } from "@/lib/product/useProjectScope";

export type { NavItem };

/** The dashboard's own URL, which is also every other row's prefix. */
const APP_ROOT = "/app";

type Pattern = { path: string; query: [string, string][] };

function parse(href: string): Pattern {
  const [path, query] = href.split("?");
  return { path, query: query ? [...new URLSearchParams(query).entries()] : [] };
}

/**
 * The sidebar: the project switcher, then the rows of the scope it is in.
 *
 * The active-link highlight is computed on the client: `usePathname()` follows the
 * router on every kind of navigation, where a server-computed highlight stuck on
 * the page you had just left after browser back/forward. The scope is too, for the
 * same reason: the layout is not re-rendered on a client-side navigation, so a
 * scope it read from the cookie would be the one you had before following a link
 * into another project.
 *
 * A row matches every page in `[href, ...also]`. A pattern with a query matches
 * only when the page has those values; on a page below the pattern's path the
 * query is not asked for (an issue's own page is still Issues). A bare path
 * matches its subtree, unless another row claims the page's query on that same
 * path — so "Get started" (/app/start) and "Settings" (/app/start?tab=connect)
 * never light up together, nor Canvas and Activity. `/app` is the prefix of
 * everything, so it only ever matches exactly.
 */
export function SideNav({ projects, initial }: { projects: ProjectOption[]; initial: string | null }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [scope, choose] = useProjectScope(initial);
  const nav: NavGroup[] = scope ? projectNav(scope) : WORKSPACE_NAV;

  const patterns = (item: NavItem) => [item[1], ...(item[2] || [])].map(parse);
  const claims = nav.flatMap(({ items }) => items.flatMap(patterns)).filter((p) => p.query.length);
  const has = (q: [string, string][]) => q.every(([k, v]) => searchParams.get(k) === v);

  const matches = ({ path, query }: Pattern) => {
    if (path === APP_ROOT) return pathname === APP_ROOT && !query.length;
    if (pathname.startsWith(`${path}/`)) return true;
    if (pathname !== path) return false;
    if (query.length) return has(query);
    return !claims.some((c) => c.path === path && has(c.query));
  };

  return (
    <>
      <ProjectSwitcher projects={projects} current={scope} onChoose={choose} />
      {nav.map(({ group, items }) => (
        <div key={group || "root"}>
          {group && <div className="group">{group}</div>}
          {items.map((item) => {
            const [label, href, , icon] = item;
            return (
              <Link key={href} href={href} className={patterns(item).some(matches) ? "active" : undefined}>
                <NavIcon href={icon || href} />
                <span>{label}</span>
              </Link>
            );
          })}
        </div>
      ))}
    </>
  );
}
