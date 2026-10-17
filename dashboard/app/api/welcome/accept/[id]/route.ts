import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** "Set this up": approve every draft agent and proposed policy one scan created. */
export async function POST(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyJson(`/api/integrations/github/scans/${encodeURIComponent(id)}/accept`, "POST", {});
}
