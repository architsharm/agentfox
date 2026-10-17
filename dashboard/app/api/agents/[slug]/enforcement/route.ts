import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Switch everything that protects this agent from watching to enforcing. */
export async function POST(_req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/enforcement`, "POST", {});
}
