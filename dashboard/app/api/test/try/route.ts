import { NextRequest, NextResponse } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/**
 * "Try it": run one message or tool call through this workspace's real rules for
 * a chosen agent. Sent as environment "playground", which every dashboard view
 * leaves out unless asked for, so testing does not show up as production traffic.
 */
export async function POST(req: NextRequest) {
  const { kind, agent, content, tool, arguments: args, source } = await req.json();
  if (!agent) return NextResponse.json({ detail: "choose an agent" }, { status: 400 });
  if (kind === "tool") {
    const provenance: Record<string, string> = {};
    for (const k of Object.keys(args || {})) provenance[k] = source || "user";
    return proxyJson("/v1/guard/tool_call", "POST", {
      agent,
      tool,
      arguments: args || {},
      provenance,
      intent: "dashboard test",
      environment: "playground",
    });
  }
  return proxyJson(kind === "output" ? "/v1/guard/output" : "/v1/guard/input", "POST", {
    agent,
    content: content || "",
    surface: kind === "output" ? "output" : "input",
    environment: "playground",
  });
}
