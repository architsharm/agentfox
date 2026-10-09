import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/**
 * Change one rule for some agents only (and, optionally, the agents they hand work
 * to). `preview: true` replays their traffic and writes nothing; without it each
 * agent's own layer is saved, live in the mode it is already in. A change that would
 * loosen a workspace rule that does not allow it comes back as 409.
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string; ruleId: string }> }) {
  const { key, ruleId } = await params;
  const b = await req.json();
  return proxyJson(`/api/policies/${encodeURIComponent(key)}/rules/${encodeURIComponent(ruleId)}/scope`, "POST", {
    agents: Array.isArray(b.agents) ? b.agents.map(String) : [],
    include_delegates: Boolean(b.include_delegates),
    preview: Boolean(b.preview),
    ...(b.effect ? { effect: b.effect } : {}),
    ...(typeof b.enabled === "boolean" ? { enabled: b.enabled } : {}),
    ...(typeof b.message === "string" ? { message: b.message } : {}),
    ...(b.on_block ? { on_block: b.on_block } : {}),
    ...(typeof b.min_score === "number" ? { min_score: b.min_score } : {}),
  });
}
