"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { WORKSPACE_NAV } from "@/lib/product/nav";
import { projectInPath } from "@/lib/product/project";

const ROWS = WORKSPACE_NAV.flatMap(({ items }) => items);

/** Where you are, as a path: "AgentFox / Map", or "AgentFox / Map / marketplace-agent" inside a project. */
export function Crumbs() {
  const pathname = usePathname() || "/app";
  const tab = useSearchParams()?.get("tab");
  const project = projectInPath(pathname);
  const row = ROWS.find(([, href, also]) =>
    [href, ...(also || [])].some((h) => {
      const path = h.split("?")[0];
      return pathname === path || pathname.startsWith(`${path}/`);
    }),
  );
  // Get started shares /app/start with two Settings tabs, but is not a setting.
  const gettingStarted = pathname === "/app/start" && tab !== "connect" && tab !== "tokens";
  const page = pathname.startsWith("/app/onboarding") ? "Guardrails" : gettingStarted ? "Get started" : row?.[0];

  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <Link href="/app">AgentFox</Link>
      {page && (
        <>
          <span className="sep">/</span>
          {project ? <Link href={row?.[1] || "/app"}>{page}</Link> : <span className="here">{page}</span>}
        </>
      )}
      {project && (
        <>
          <span className="sep">/</span>
          <span className="here">{project}</span>
        </>
      )}
    </nav>
  );
}
