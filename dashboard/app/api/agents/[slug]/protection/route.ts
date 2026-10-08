import { NextRequest } from "next/server";
import { protectionSetup } from "@/lib/product/protection";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Save an agent's protections, words, topics and blocked message. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/protection`, "POST", protectionSetup(await req.json()));
}

