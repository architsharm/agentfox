import { proxyJson } from "@/lib/product/proxy";

/** One agent's guardrail map: what guards each step. */
export async function GET(_req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/map`, "GET", undefined, { cache: "no-store" });
}
