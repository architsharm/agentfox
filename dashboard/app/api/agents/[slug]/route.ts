import { proxyJson } from "@/lib/product/proxy";

/** One agent: its name, its project, how it is set up. */
export async function GET(_req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}`, "GET", undefined, { cache: "no-store" });
}
