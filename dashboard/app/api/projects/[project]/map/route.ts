import { proxyJson } from "@/lib/product/proxy";

/** One project's agents, tools and what they reach. */
export async function GET(_req: Request, { params }: { params: Promise<{ project: string }> }) {
  const { project } = await params;
  return proxyJson(`/api/projects/${encodeURIComponent(project)}/map`, "GET", undefined, { cache: "no-store" });
}
