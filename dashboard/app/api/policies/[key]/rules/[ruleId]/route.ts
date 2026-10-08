import { NextRequest, NextResponse } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/**
 * Change one rule: save it as a new version of its pack, then — when the pack is
 * enforcing — record a simulation of that version over recent traffic, which is
 * both what the customer needs to see before applying and what the gateway
 * requires before it will make an enforcing version live. Nothing changes in
 * force until the version is applied (POST ../../mode with the version).
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string; ruleId: string }> }) {
  const { key, ruleId } = await params;
  const { effect, enabled, message, on_block, min_score, agent } = await req.json();
  const saved = await proxyJson(`/api/policies/${encodeURIComponent(key)}/rules/${encodeURIComponent(ruleId)}`, "POST", {
    ...(effect ? { effect } : {}),
    ...(enabled === undefined ? {} : { enabled }),
    ...(typeof message === "string" ? { message } : {}),
    ...(on_block ? { on_block } : {}),
    ...(typeof min_score === "number" ? { min_score } : {}),
  });
  if (!saved.ok) return saved;
  const version = await saved.json();
  const sim = await proxyJson("/api/policies/simulate", "POST", {
    body: version.body,
    ...(agent ? { agent } : {}),
    since_days: 7,
    persist: Boolean(version.needs_simulation),
  });
  const simulation = sim.ok ? await sim.json() : null;
  return NextResponse.json({ ...version, simulation });
}
