import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Drop this agent's own change to a rule, so the workspace rule applies again. */
export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ slug: string; ruleId: string }> }) {
  const { slug, ruleId } = await params;
  return proxyJson(`/api/policies/agents/${encodeURIComponent(slug)}/rules/${encodeURIComponent(ruleId)}`, "DELETE");
}
