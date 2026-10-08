import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Install a shipped pack, watching. The id can contain a slash (payments/refunds). */
export async function POST(_req: Request, { params }: { params: Promise<{ id: string[] }> }) {
  const { id } = await params;
  const packId = id.map(encodeURIComponent).join("/");
  return proxyJson(`/api/library/packs/${packId}/install`, "POST");
}
