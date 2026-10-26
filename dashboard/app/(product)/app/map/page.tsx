import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { safeApi } from "@/lib/product/api";
import { MAP_PROJECT_COOKIE, NEW_PROJECT, projectHref } from "@/lib/product/project";

export const dynamic = "force-dynamic";

/**
 * "Agents" in the sidebar: the chosen project's own page, whose canvas is the map. The
 * project is the one in the URL, else the one last chosen, else the most recently
 * mapped. With no project yet, setup.
 */
export default async function MapPage({ searchParams }: { searchParams: Promise<{ project?: string }> }) {
  const [{ project: asked }, jar, { projects }] = await Promise.all([
    searchParams,
    cookies(),
    safeApi<any>("/api/projects", { projects: [] }),
  ]);
  // Adding a project: the app chrome shows the connection card in place of this page.
  if (!asked && jar.get(MAP_PROJECT_COOKIE)?.value === NEW_PROJECT) return null;
  const names: string[] = (projects ?? []).map((p: any) => p.project);
  // No project yet: the app chrome shows the connection card in place of this page.
  if (names.length === 0) return null;
  const chosen = [asked, jar.get(MAP_PROJECT_COOKIE)?.value].find((p) => p && names.includes(p)) ?? names[0];
  const map = await safeApi<any>(`/api/projects/${encodeURIComponent(chosen)}/map`, null);
  const agent = map?.agents?.[0]?.slug;
  redirect(agent ? projectHref(agent) : "/app/onboarding");
}
