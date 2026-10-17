import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";
import { protectionSetup } from "@/lib/product/protection";

export const dynamic = "force-dynamic";

/** Replay the agent's last week against a setup. Saves nothing. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/protection/preview`, "POST", protectionSetup(await req.json()));
}
