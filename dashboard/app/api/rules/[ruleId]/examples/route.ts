import { NextRequest, NextResponse } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/**
 * Save a test for a rule: run the text through the playground for the chosen agent
 * (so it is recorded, but not counted as production traffic), then keep that decision
 * with whether the rule should fire on it.
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ ruleId: string }> }) {
  const { ruleId } = await params;
  const { text, surface, agent, fires } = await req.json();
  if (!agent || !String(text || "").trim()) return NextResponse.json({ detail: "choose an agent and enter text" }, { status: 400 });
  const ran = await proxyJson(surface === "output" ? "/v1/guard/output" : "/v1/guard/input", "POST", {
    agent: String(agent),
    content: String(text),
    surface: surface === "output" ? "output" : "input",
    environment: "playground",
  });
  if (!ran.ok) return ran;
  const { decision_id } = await ran.json();
  return proxyJson(`/api/rules/${encodeURIComponent(ruleId)}/examples`, "POST", {
    decision_id,
    fires: Boolean(fires),
    sample: String(text).slice(0, 2000),
  });
}
