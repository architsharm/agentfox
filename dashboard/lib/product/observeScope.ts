import { cookies } from "next/headers";
import { safeApi } from "@/lib/product/api";
import { MAP_PROJECT_COOKIE, NEW_PROJECT } from "@/lib/product/project";

/**
 * Which agents an Observe page shows: the project chosen in the sidebar's switcher
 * (one project at a time, never all of them mixed), or just the agent the URL names.
 */
export async function observeScope(agent?: string): Promise<{ project: string | null; agents: string[] }> {
  if (agent) return { project: null, agents: [agent] };
  const [jar, { projects }] = await Promise.all([cookies(), safeApi<any>("/api/projects", { projects: [] })]);
  if (jar.get(MAP_PROJECT_COOKIE)?.value === NEW_PROJECT) return { project: null, agents: [] };
  const names: string[] = (projects ?? []).map((p: any) => p.project);
  const project = [jar.get(MAP_PROJECT_COOKIE)?.value].find((p) => p && names.includes(p)) ?? names[0] ?? null;
  if (!project) return { project: null, agents: [] };
  const map = await safeApi<any>(`/api/projects/${encodeURIComponent(project)}/map`, null);
  return { project, agents: (map?.agents ?? []).map((a: any) => a.slug) };
}

/** `agent=` for the API when the scope is one agent; the rest is filtered here. */
export function agentQuery(agents: string[]): string {
  return agents.length === 1 ? `agent=${encodeURIComponent(agents[0])}&` : "";
}
