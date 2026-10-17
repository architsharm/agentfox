import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Switch a check on or off for every project, or (with `agent`) for one. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const { enabled, agent, reason } = await req.json();
  return proxyJson(`/api/features/checks/${encodeURIComponent(key)}`, "POST", {
    enabled: Boolean(enabled),
    agent: String(agent || ""),
    reason: String(reason || ""),
  });
}
