import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Grant a tool to an agent, or change its existing grant. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const { tool_key, requires_approval, max_taint, constraints, actions } = await req.json();
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/access`, "POST", {
    tool_key,
    requires_approval: Boolean(requires_approval),
    max_taint: max_taint || "user",
    constraints: constraints || {},
    ...(actions ? { actions } : {}),
  });
}
