import { proxyJson } from "@/lib/product/proxy";

/** Disconnect a project: its agents leave the dashboard; `agentfox init` brings it back as new. */
export async function DELETE(_req: Request, { params }: { params: Promise<{ project: string }> }) {
  const { project } = await params;
  return proxyJson(`/api/projects/${encodeURIComponent(project)}`, "DELETE");
}
