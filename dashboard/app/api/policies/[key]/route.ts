import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Remove an imported policy: its rules stop applying; its versions stay. */
export async function DELETE(_req: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return proxyJson(`/api/policies/${encodeURIComponent(key)}`, "DELETE");
}
