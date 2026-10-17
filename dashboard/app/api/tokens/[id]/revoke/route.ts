import { proxyJson } from "@/lib/product/proxy";

export async function POST(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyJson(`/api/tokens/${id}/revoke`, "POST");
}
