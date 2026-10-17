"use client";

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { PROJECT_COOKIE, PROJECT_COOKIE_AGE, projectInPath } from "@/lib/product/project";

function remember(slug: string | null) {
  document.cookie = slug
    ? `${PROJECT_COOKIE}=${encodeURIComponent(slug)}; path=/; max-age=${PROJECT_COOKIE_AGE}; samesite=lax`
    : `${PROJECT_COOKIE}=; path=/; max-age=0; samesite=lax`;
}

/**
 * The scope the sidebar is in: the project the page names, if it names one,
 * otherwise the one last chosen. A project's own page names it in its path; a
 * workspace page filtered to one project (`?agent=`) names it too, so following
 * "Issues" from a project keeps you in it. The projects list is all projects.
 *
 * Returns the scope and a way to choose one, which the switcher uses.
 */
export function useProjectScope(initial: string | null): [string | null, (slug: string | null) => void] {
  const pathname = usePathname();
  const agent = useSearchParams().get("agent");
  const [chosen, setChosen] = useState<string | null>(initial);

  const named: string | null | undefined =
    projectInPath(pathname) ?? (pathname === "/app/projects" ? null : agent || undefined);
  const scope = named === undefined ? chosen : named;

  // Only when the page changes to name another project: choosing All projects
  // from a project's page happens while that page still names the project.
  useEffect(() => {
    if (named === undefined) return;
    setChosen(named);
    remember(named);
  }, [named]);

  const choose = (slug: string | null) => {
    setChosen(slug);
    remember(slug);
  };
  return [scope, choose];
}
