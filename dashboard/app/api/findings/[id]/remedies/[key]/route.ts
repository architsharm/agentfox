import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Take one of an issue's actions. The gateway audits it and closes the issue if it cleared. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string; key: string }> }) {
  const { id, key } = await params;
  const { inputs } = await req.json().catch(() => ({ inputs: {} }));
  return proxyJson(`/api/findings/${encodeURIComponent(id)}/remedies/${encodeURIComponent(key)}`, "POST", { inputs: inputs || {} });
}
