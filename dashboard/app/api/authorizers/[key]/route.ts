import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function DELETE(_req: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return proxyJson(`/api/authorizers/${encodeURIComponent(key)}`, "DELETE");
}
