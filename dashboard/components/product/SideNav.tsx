"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { NavIcon } from "@/components/product/NavIcons";
import { ProjectSwitcher, type ProjectOption } from "@/components/product/ProjectSwitcher";
import { WORKSPACE_NAV, type NavGroup, type NavItem } from "@/lib/product/nav";
import { MAP_PROJECT_COOKIE, NEW_PROJECT, PROJECT_COOKIE_AGE, projectInPath, switcherOptions } from "@/lib/product/project";

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
 * path — so a row with a query and the bare row on that path
 * never light up together. `/app` is the prefix of
 * everything, so it only ever matches exactly.
 */
export function SideNav({ projects, initial }: { projects: ProjectOption[]; initial: string | null }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // The Map follows the project in its URL, else the one last chosen.
  // On an agent's page, the switcher shows that agent's project when it is one.
  const inPath = projectInPath(pathname);
  // One row per repository, as the map draws it (see switcherOptions).
  const options = switcherOptions(projects);
  const optionOf = (key: string | null) => (key ? (options.find((p) => p.project === key || p.slugs?.includes(key))?.project ?? null) : null);
  // An agent's page belongs to that agent's project (several agents can share one).
  const opened = optionOf(inPath);
  const asked = pathname === "/app/map" ? searchParams.get("project") : null;
  const current = optionOf(asked) || asked || opened || (initial === NEW_PROJECT ? initial : optionOf(initial) || initial);
  // Opening a project's page is choosing it: every other page follows, and a project
  // still being added is left.
  const router = useRouter();
  useEffect(() => {
    if (!opened || opened === initial) return;
    document.cookie = `${MAP_PROJECT_COOKIE}=${encodeURIComponent(opened)}; path=/; max-age=${PROJECT_COOKIE_AGE}; samesite=lax`;
    router.refresh();
  }, [opened, initial, router]);
  const nav: NavGroup[] = WORKSPACE_NAV;

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
      <ProjectSwitcher projects={options} current={current} />
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
