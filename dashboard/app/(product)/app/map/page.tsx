import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { MAP_PROJECT_COOKIE, NEW_PROJECT, defaultProject, openingAgent, projectHref, switcherOptions } from "@/lib/product/project";

// Named like its sidebar row; without a project it stays on this URL showing setup.
export const metadata: Metadata = appPageMetadata("Agents");
export const dynamic = "force-dynamic";

/**
 * "Agents" in the sidebar: the chosen project's own page, whose canvas is the map. The
 * project is the one in the URL, else the one last chosen, else the most recently
 * active. It opens on the project's agent that was active last (an added one before a
 * proposal), else its root. With no project yet, setup.
 */
export default async function MapPage({ searchParams }: { searchParams: Promise<{ project?: string }> }) {
  const [{ project: asked }, jar, { projects }] = await Promise.all([
    searchParams,
    cookies(),
    safeApi<any>("/api/projects", { projects: [] }),
  ]);
  // Adding a project: the app chrome shows the connection card in place of this page.
  if (!asked && jar.get(MAP_PROJECT_COOKIE)?.value === NEW_PROJECT) return null;
  // One option per repository, as the switcher offers them; an old cookie naming a
  // system's root (or any agent) lands on the option that holds it.
  const options = switcherOptions(projects ?? []);
  // No project yet: the app chrome shows the connection card in place of this page.
  if (options.length === 0) return null;
  const optionOf = (key?: string | null) => (key ? options.find((o) => o.project === key || o.slugs?.includes(key))?.project : undefined);
  const chosen = optionOf(asked) ?? optionOf(jar.get(MAP_PROJECT_COOKIE)?.value) ?? defaultProject(options)!.project;
  const [map, all] = await Promise.all([
    safeApi<any>(`/api/projects/${encodeURIComponent(chosen)}/map`, null),
    safeApi<any>("/api/agents", { agents: [] }),
  ]);
  const agent = openingAgent(map?.agents ?? [], all.agents ?? []);
  // A project whose map has no agent (or a map that did not load): the list of projects,
  // not /app/onboarding, which redirects straight back here.
  redirect(agent ? projectHref(agent) : "/app/projects");
}
