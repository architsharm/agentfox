import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** This project goes back to the workspace's setting. */
export async function DELETE(_req: Request, { params }: { params: Promise<{ slug: string; key: string }> }) {
  const { slug, key } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/features/checks/${encodeURIComponent(key)}`, "DELETE");
}
