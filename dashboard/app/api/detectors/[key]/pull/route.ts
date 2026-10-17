import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Download an open-source detector's model on the gateway, in a background job. */
export async function POST(_req: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return proxyJson(`/api/detectors/${encodeURIComponent(key)}/pull`, "POST");
}
