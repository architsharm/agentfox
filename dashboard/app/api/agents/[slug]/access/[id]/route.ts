import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Remove one grant from an agent. */
export async function DELETE(_req: Request, { params }: { params: Promise<{ slug: string; id: string }> }) {
  const { slug, id } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/access/${encodeURIComponent(id)}`, "DELETE");
}
