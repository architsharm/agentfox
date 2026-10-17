import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Delete a custom rule; its rule leaves the custom pack in a new version. */
export async function DELETE(_req: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return proxyJson(`/api/custom-rules/${encodeURIComponent(key)}`, "DELETE");
}
