"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { WORKSPACE_NAV } from "@/lib/product/nav";
import { projectInPath } from "@/lib/product/project";

const ROWS = WORKSPACE_NAV.flatMap(({ items }) => items);

/** The sidebar row a page belongs to, by its path. */
export function crumbFor(pathname: string): string | undefined {
  // The step-by-step test flow is part of setting up an agent: under Agents, like its setup card.
  if (pathname.startsWith("/app/onboarding")) return "Agents";
  const row = ROWS.find(([, href, also]) =>
    [href, ...(also || [])].some((h) => {
      const path = h.split("?")[0];
      return pathname === path || pathname.startsWith(`${path}/`);
    }),
  );
  return row?.[0];
}

/** Where you are, as a path: "AgentFox / Agents", or "AgentFox / Agents / Billing support" inside an agent, by its name. */
export function Crumbs() {
  const pathname = usePathname() || "/app";
  const project = projectInPath(pathname);
  const page = crumbFor(pathname);
  const href = ROWS.find(([label]) => label === page)?.[1] || "/app";
  // The agent's name, as its page title shows it; the slug until it answers.
  const [name, setName] = useState<{ slug: string; name: string } | null>(null);
  useEffect(() => {
    if (!project) return;
    let stop = false;
    fetch(`/api/agents/${encodeURIComponent(project)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((a) => !stop && a?.name && setName({ slug: project, name: a.name }))
      .catch(() => {});
    return () => {
      stop = true;
    };
  }, [project]);

  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <Link href="/app">AgentFox</Link>
      {page && (
        <>
          <span className="sep">/</span>
          {project ? <Link href={href}>{page}</Link> : <span className="here">{page}</span>}
        </>
      )}
      {project && (
        <>
          <span className="sep">/</span>
          <span className="here">{name?.slug === project ? name.name : project}</span>
        </>
      )}
    </nav>
  );
}
