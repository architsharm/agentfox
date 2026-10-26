import { proxyJson } from "@/lib/product/proxy";

/** Add a project's proposed agents (what `agentfox init` found) to the workspace. */
export async function POST(_req: Request, { params }: { params: Promise<{ project: string }> }) {
  const { project } = await params;
  return proxyJson(`/api/projects/${encodeURIComponent(project)}/approve`, "POST");
}
