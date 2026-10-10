import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** What enforcing would switch on for this agent, and what it would have stopped. */
export async function POST(_req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/enforcement/preview`, "POST", {});
}
